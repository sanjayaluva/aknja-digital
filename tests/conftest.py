"""Test fixtures: real PostgreSQL per session, clean state per test.

The suite runs against a genuine PostgreSQL instance (pgserver) because the
data model uses PostgreSQL-specific features (JSONB, audit triggers, row
locks). CI runs the same suite against a PostgreSQL service container.
"""

from __future__ import annotations

import os

# --- Environment must be pinned BEFORE any app import. ---
_TEST_DB_NAME = "aknja_test"
_PGDATA = "/home/z/my-project/pgdata-aknja"

if os.environ.get("AKNJA_TEST_DATABASE_URL"):
    _DATABASE_URL = os.environ["AKNJA_TEST_DATABASE_URL"]
else:
    import re

    import pgserver

    _server = pgserver.get_server(_PGDATA)
    _uri = _server.get_uri()  # postgresql://postgres:@/postgres?host=...
    _m = re.match(r"postgresql://([^:]*):([^@]*)@/([^?]+)\?host=(.+)", _uri)
    assert _m is not None
    _user, _password, _dbname, _host = _m.groups()
    import psycopg

    with psycopg.connect(_uri, autocommit=True) as _conn:
        _conn.execute(f"DROP DATABASE IF EXISTS {_TEST_DB_NAME} WITH (FORCE)")
        _conn.execute(f"CREATE DATABASE {_TEST_DB_NAME}")
    _DATABASE_URL = f"postgresql+psycopg://{_user}:{_password}@/{_TEST_DB_NAME}?host={_host}"

os.environ["DATABASE_URL"] = _DATABASE_URL
# NOTE: "local" (not "ci") so session cookies are not Secure-flagged —
# the ASGI test transport is plain HTTP.
os.environ["APP_ENV"] = "local"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production-0123456789"
os.environ["LOG_LEVEL"] = "ERROR"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import Base, create_testing_engine, reset_engine
from app.core.enums import UserRole
from app.modules.identity import service as identity

ADMIN_EMAIL = "founder@example.com"
ADMIN_PASSWORD = "FounderPass#1"


@pytest.fixture(scope="session")
def engine():
    reset_engine()
    os.environ["DATABASE_URL"] = _DATABASE_URL
    import app.models  # noqa: F401

    eng = create_testing_engine(_DATABASE_URL)
    Base.metadata.create_all(eng)
    # Install the DB-level audit immutability trigger on the test database.
    from sqlalchemy.orm import Session as _Session

    with _Session(eng) as db:
        from app.modules.governance.service import install_audit_immutability_trigger

        install_audit_immutability_trigger(db)
    yield eng
    eng.dispose()
    reset_engine()


@pytest.fixture
def db(engine):
    """Fresh session with a clean database for every test."""
    import app.models  # noqa: F401 — ensure all models registered

    tables = ", ".join(f'"{t}"' for t in reversed(Base.metadata.sorted_tables))
    with engine.connect() as conn:
        # TRUNCATE is not blocked by the UPDATE/DELETE append-only trigger.
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        conn.commit()
    session = Session(engine, expire_on_commit=False)
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="session")
def app():
    reset_engine()
    os.environ["DATABASE_URL"] = _DATABASE_URL
    from app.main import create_app

    application = create_app()
    yield application
    reset_engine()


@pytest.fixture
def client(app):
    """Anonymous HTTP client (lifespan runs once per client context)."""
    with TestClient(app) as c:
        yield c


def _make_session(engine):
    return Session(engine, expire_on_commit=False)


@pytest.fixture
def seed(db: Session, engine):
    """Seed the internal tenant + super admin + base data; returns helpers."""

    class Seeded:
        pass

    seeded = Seeded()
    tenant = identity.bootstrap_internal_tenant(db)
    admin = identity.create_user(
        db,
        email=ADMIN_EMAIL,
        password=ADMIN_PASSWORD,
        full_name="Test Founder",
        tenant_id=tenant.id,
        role=UserRole.SUPER_ADMIN,
    )
    db.commit()

    from app.modules.ai.gateway import seed_builtin_tools
    from app.modules.ai.orchestrator import seed_capabilities
    from app.modules.ops.settings_service import seed_settings

    with _make_session(engine) as s:
        t = identity.bootstrap_internal_tenant(s)
        seed_settings(s)
        seed_capabilities(s, t.id)
        seed_builtin_tools(s)
        s.commit()

    seeded.tenant = tenant
    seeded.admin = admin
    yield seeded


class AuthClient:
    """Cookie-authenticated client with an ISOLATED cookie jar and CSRF headers.

    Each AuthClient wraps its own TestClient so logging in as a second user
    never overwrites the first user's session cookie.
    """

    def __init__(self, app, email: str, password: str) -> None:
        self._client = TestClient(app)
        resp = self._client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert resp.status_code == 200, resp.text
        info = resp.json()
        self.csrf = info["csrf_token"]
        self.user_id = info["user_id"]
        self.tenant_id = info["tenant_id"]
        self.role = info["role"]

    def _headers(self, json_body: bool = True) -> dict:
        return {"x-csrf-token": self.csrf}

    def get(self, url: str, **kw):
        return self._client.get(url, **kw)

    def post(self, url: str, json=None, **kw):
        return self._client.post(url, json=json, headers=self._headers(), **kw)

    def patch(self, url: str, json=None, **kw):
        return self._client.patch(url, json=json, headers=self._headers(), **kw)

    def put(self, url: str, json=None, **kw):
        return self._client.put(url, json=json, headers=self._headers(), **kw)


@pytest.fixture
def admin_client(app, seed) -> AuthClient:
    return AuthClient(app, ADMIN_EMAIL, ADMIN_PASSWORD)


def make_user(db: Session, *, email: str, password: str, tenant_id, role: UserRole, client_id=None):
    return identity.create_user(
        db, email=email, password=password, tenant_id=tenant_id, role=role, client_id=client_id
    )


def make_tenant(db: Session, name: str, slug: str):
    from app.modules.identity.models import Tenant

    tenant = Tenant(name=name, slug=slug)
    db.add(tenant)
    db.flush()
    return tenant
