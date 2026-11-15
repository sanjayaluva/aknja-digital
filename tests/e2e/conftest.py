"""Playwright E2E harness (docs/16, round T-007).

Boots the real FastAPI app with uvicorn on a free localhost port against a
dedicated scratch PostgreSQL database (migrated via alembic, deterministically
seeded, timestamps frozen for reproducible screenshots). The functional E2E
tests drive real browser flows; the visual tests compare full-page screenshots
against committed baselines with an explicit pixel-diff tolerance
(docs/16: controlled visual diff; dynamic-content screens — e.g. the audit
log with live timestamps — are excluded from baselines by policy).

Reseeding uses TRUNCATE on the live database (never DROP DATABASE) so the
running app's pooled connections stay valid. Skips cleanly (pytest.skip)
when Chromium is unavailable.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pgserver
import psycopg
import pytest

# --- scratch database -----------------------------------------------------------

# Repo root (this file: <repo>/tests/e2e/conftest.py) — never hardcode machine
# paths; CI checkouts live elsewhere and the cluster dir is gitignored.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PGDATA = str(_REPO_ROOT / "pgdata-aknja-e2e")
DB_NAME = "aknja_e2e"
# CI / external-database override: when set, no pgserver cluster is started and
# the suite runs against this URL (service container in CI).
E2E_DB_URL = os.environ.get("AKNJA_E2E_DATABASE_URL")
FROZEN_TS = "2026-11-15 12:00:00+00"

E2E_FOUNDER_EMAIL = "founder@example.com"
E2E_FOUNDER_PASSWORD = "FounderE2E#1"
E2E_CLIENT_EMAIL = "client@example.com"
E2E_CLIENT_PASSWORD = "ClientE2E#1"

LEAD_TITLE = "Bakery website enquiry"
PROJECT_NAME = "Sweet Cakes website"


def _db_url() -> str:
    if E2E_DB_URL:
        return E2E_DB_URL
    uri = pgserver.get_server(PGDATA).get_uri()
    m = re.match(r"postgresql://([^:]*):([^@]*)@/([^?]+)\?host=(.+)", uri)
    assert m, uri
    user, password, _db, host = m.groups()
    return f"postgresql+psycopg://{user}:{password}@/{DB_NAME}?host={host}"


def _prepare_database() -> None:
    """Create the scratch DB once per session: migrate + audit trigger.

    pgserver path: drop/create the scratch DB on the bundled cluster.
    AKNJA_E2E_DATABASE_URL path (CI): the database must already exist
    (workflow creates it); alembic is idempotent and the seed truncates.
    """
    if not E2E_DB_URL:
        uri = pgserver.get_server(PGDATA).get_uri()
        with psycopg.connect(uri, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {DB_NAME}")
    r = subprocess.run(  # noqa: PLW1510 — returncode checked below
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "DATABASE_URL": _db_url()},
        cwd=str(_REPO_ROOT),
    )
    if r.returncode != 0:
        raise RuntimeError(f"alembic upgrade failed:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")

    os.environ["DATABASE_URL"] = _db_url()
    from app.core.config import get_settings
    from app.core.db import get_engine, reset_engine

    get_settings.cache_clear()
    reset_engine()
    from sqlalchemy.orm import Session

    import app.models  # noqa: F401 — register every model

    with Session(get_engine()) as db:
        from app.modules.governance.service import install_audit_immutability_trigger

        install_audit_immutability_trigger(db)
        db.commit()


def _seed(db) -> None:
    """Deterministic seed: founder, client user, lead, project+task, approval,
    catalog taxonomy, candidate provider pool."""
    from pathlib import Path

    from app.core.enums import UserRole
    from app.modules.crm import service as crm
    from app.modules.delivery import service as delivery
    from app.modules.governance.service import create_approval_request
    from app.modules.identity import service as identity
    from app.modules.identity.service import Principal

    tenant = identity.bootstrap_internal_tenant(db)
    founder = identity.create_user(
        db, email=E2E_FOUNDER_EMAIL, password=E2E_FOUNDER_PASSWORD,
        full_name="E2E Founder", tenant_id=tenant.id, role=UserRole.SUPER_ADMIN,
    )
    from app.modules.ai.gateway import seed_builtin_tools
    from app.modules.ai.orchestrator import seed_capabilities
    from app.modules.ops.settings_service import seed_settings

    seed_settings(db)
    seed_capabilities(db, tenant.id)
    seed_builtin_tools(db)

    from app.modules.catalog.service import import_taxonomy

    root = Path(__file__).resolve().parents[2]
    import_taxonomy(
        db, tenant_id=tenant.id,
        md_path=root / "docs" / "source_service_hierarchy.md",
        seed_csv_path=root / "examples" / "service-readiness-seed.csv",
    )

    from app.modules.resources.candidates import register_candidate_providers

    register_candidate_providers(db, tenant.id)

    principal = Principal(
        user_id=founder.id, email=founder.email, tenant_id=tenant.id,
        role=UserRole.SUPER_ADMIN, client_id=None, session_id=founder.id,
        csrf_token="e2e-seed",
    )
    crm.create_lead(
        db, principal=principal, title=LEAD_TITLE, source="REFERRAL",
        description="Kochi bakery needs a website with online orders.",
        contact_email="owner@sweetcakes.example", budget_minor=500000,
        feasibility_score=70,
    )
    client = crm.create_client(
        db, principal=principal, display_name="Sweet Cakes",
        email="owner@sweetcakes.example", phone="+91 98765 43210",
    )
    from app.modules.crm.models import ClientStatus

    client.status = ClientStatus.ACTIVE.value
    project = delivery.create_project(
        db, principal=principal, client_id=client.id, name=PROJECT_NAME,
        description="Five-page bakery website with online order form.",
    )
    delivery.create_task(
        db, tenant_id=tenant.id, project_id=project.id,
        title="Design home page", priority="HIGH", estimate_hours=6,
    )
    create_approval_request(
        db, tenant_id=tenant.id, gate="provider.override",
        title="Enable paid provider override (E2E seed)",
        payload={"provider": "example", "reason": "E2E seed data"},
        summary_ml="E2E സീഡ് ഡാറ്റ",
    )
    identity.create_user(
        db, email=E2E_CLIENT_EMAIL, password=E2E_CLIENT_PASSWORD,
        full_name="Sweet Cakes Owner", tenant_id=tenant.id,
        role=UserRole.CLIENT_OWNER, client_id=client.id,
    )
    db.commit()


def reseed() -> None:
    """Restore the exact seeded state on the live database (repeatable).

    TRUNCATE (unlike UPDATE/DELETE) is not blocked by the audit append-only
    trigger, and never invalidates the running app's pooled connections.
    """
    from sqlalchemy import text

    from app.core.db import Base, get_engine

    engine = get_engine()
    with engine.connect() as conn:
        tables = ", ".join(f'"{t}"' for t in reversed(Base.metadata.sorted_tables))
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        conn.commit()
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        _seed(db)
        # Freeze created/updated timestamps for reproducible screenshots. The
        # audit ledger is append-only (DB trigger) and excluded — /admin/audit
        # is not part of the visual baselines (docs/16 explicit exclusion).
        for table in Base.metadata.sorted_tables:
            if table.name.startswith("audit"):
                continue
            cols = {c.name for c in table.columns}
            sets = [f'"{c}" = \'{FROZEN_TS}\'' for c in ("created_at", "updated_at") if c in cols]
            if sets:
                db.execute(text(f'UPDATE "{table.name}" SET {", ".join(sets)}'))
        db.commit()


@pytest.fixture(scope="session")
def server_url():
    """Real uvicorn server on a free port against the scratch DB."""
    if os.environ.get("AKNJA_E2E") == "skip":
        pytest.skip("AKNJA_E2E=skip")
    os.environ.setdefault("APP_ENV", "local")  # plain HTTP cookies
    os.environ.setdefault("SECRET_KEY", "e2e-secret-key-not-for-production")
    os.environ.setdefault("LOG_LEVEL", "ERROR")
    _prepare_database()
    reseed()

    from app.main import create_app

    application = create_app()

    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = uvicorn.Config(application, host="127.0.0.1", port=port,
                            log_level="error")
    uvi = uvicorn.Server(config)
    thread = threading.Thread(target=uvi.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base}/healthz", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        pytest.fail("E2E server did not become healthy")
    # Warm the cold paths (template compilation, engine pool, settings) so the
    # first login on a slow 2-core CI runner is not a 10s+ outlier.
    for path in ("/login", "/healthz/ready"):
        try:
            httpx.get(f"{base}{path}", timeout=15)
        except httpx.HTTPError:
            pass
    yield base
    uvi.should_exit = True
    thread.join(timeout=10)
    # Leave the process clean for any fixture instantiated afterwards (the
    # main suite runs after tests/e2e* alphabetically): drop the cached
    # settings bound to the scratch DB and the global engine.
    from app.core.config import get_settings
    from app.core.db import reset_engine

    get_settings.cache_clear()
    reset_engine()


@pytest.fixture(scope="session")
def browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    try:
        pw = sync_playwright().start()
        chrom = pw.chromium.launch(headless=True)
    except Exception as exc:  # noqa: BLE001 — any launch failure means skip
        pytest.skip(f"chromium unavailable: {exc}")
    yield chrom
    chrom.close()
    pw.stop()


@pytest.fixture
def page(browser, server_url):
    """Fresh browser context (isolated cookies) per test, desktop viewport."""
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    yield context.new_page()
    context.close()


def current_seed_ids() -> dict[str, str]:
    """Ids of the seeded lead/project/client in the CURRENT database state."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from app.core.db import get_engine

    with Session(get_engine()) as db:
        row = db.execute(text(
            "SELECT (SELECT id FROM leads ORDER BY created_at LIMIT 1), "
            "(SELECT id FROM projects ORDER BY created_at LIMIT 1), "
            "(SELECT id FROM clients ORDER BY created_at LIMIT 1)"
        )).one()
    return {"lead_id": str(row[0]), "project_id": str(row[1]), "client_id": str(row[2])}


@pytest.fixture(scope="session")
def seed_ids(server_url):
    return current_seed_ids()


def login(page, base_url: str, email: str, password: str) -> None:
    """Real login through the htmx form: fill, submit, wait for the redirect."""
    page.goto(f"{base_url}/login")
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    # 30s: the first login on a cold CI runner (argon2 + session + audit
    # writes + template compile) can exceed a tight 10s budget.
    page.wait_for_url(lambda url: "/admin" in url or "/portal" in url, timeout=30_000)
