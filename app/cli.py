"""Management CLI.

Usage:
  python -m app.cli init-db                 # create schema (dev/bootstrap only)
  python -m app.cli create-super-admin      # interactive/argv super admin bootstrap
  python -m app.cli import-taxonomy         # import the source service taxonomy
  python -m app.cli seed                    # settings + capabilities + tools
  python -m app.cli verify-install          # post-install verification evidence

Production databases are managed by Alembic migrations
(`alembic upgrade head`); `init-db` is for local/bootstrap use.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

import app.models  # noqa: F401 — register every model for the CLI
from app.core.config import get_settings
from app.core.db import Base, get_engine, get_session_local
from app.core.enums import UserRole


def cmd_init_db(_args: argparse.Namespace) -> int:

    engine = get_engine()
    Base.metadata.create_all(engine)
    db = get_session_local()()
    try:
        from app.modules.governance.service import (
            get_emergency_stop,
            install_audit_immutability_trigger,
        )
        from app.modules.identity.service import bootstrap_internal_tenant

        tenant = bootstrap_internal_tenant(db)
        get_emergency_stop(db)
        db.commit()
        if engine.url.get_backend_name() == "postgresql":
            install_audit_immutability_trigger(db)
        else:
            print("note: audit immutability trigger requires PostgreSQL")
        print(f"OK schema created. Internal tenant: {tenant.id}")
    finally:
        db.close()
    return 0


def cmd_create_super_admin(args: argparse.Namespace) -> int:
    db = get_session_local()()
    try:
        from app.modules.identity.service import bootstrap_internal_tenant, create_user

        tenant = bootstrap_internal_tenant(db)
        email = args.email or input("Super admin email: ").strip()
        password = args.password or getpass.getpass("Password (min 8 chars): ")
        if len(password) < 8:
            print("ERROR: password must be at least 8 characters")
            return 1
        user = create_user(
            db, email=email, password=password, full_name="Founder",
            tenant_id=tenant.id, role=UserRole.SUPER_ADMIN,
        )
        db.commit()
        print(f"OK super admin created: {user.email} (tenant {tenant.id})")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_import_taxonomy(args: argparse.Namespace) -> int:
    db = get_session_local()()
    try:
        from app.modules.catalog.service import import_taxonomy
        from app.modules.identity.service import bootstrap_internal_tenant

        tenant = bootstrap_internal_tenant(db)
        repo_root = Path(__file__).resolve().parent.parent
        md = Path(args.md) if args.md else repo_root / "docs" / "source_service_hierarchy.md"
        csv_path = Path(args.csv) if args.csv else repo_root / "examples" / "service-readiness-seed.csv"
        stats = import_taxonomy(
            db, tenant_id=tenant.id, md_path=md, seed_csv_path=csv_path if csv_path.exists() else None
        )
        db.commit()
        print(f"OK taxonomy imported: {stats}")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_seed(_args: argparse.Namespace) -> int:
    db = get_session_local()()
    try:
        from app.modules.ai.gateway import seed_builtin_tools
        from app.modules.ai.orchestrator import seed_capabilities
        from app.modules.identity.service import bootstrap_internal_tenant
        from app.modules.ops.settings_service import seed_settings

        tenant = bootstrap_internal_tenant(db)
        settings_created = seed_settings(db)
        capabilities = seed_capabilities(db, tenant.id)
        tools = seed_builtin_tools(db)
        db.commit()
        print(
            f"OK seeded: {settings_created} new settings, "
            f"{len(capabilities)} capabilities, {len(tools)} tools"
        )
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_verify_install(_args: argparse.Namespace) -> int:
    """Post-install verification evidence (docs/40 checklist)."""
    db = get_session_local()()
    try:
        from sqlalchemy import func, select

        from app.core.security import verify_password
        from app.modules.ai.models import AgentCapability, ToolDefinition
        from app.modules.catalog.models import Service
        from app.modules.governance.models import AuditEvent
        from app.modules.governance.service import verify_audit_chain
        from app.modules.identity.models import Tenant, TenantMembership
        from app.modules.ops.models import SystemSetting

        checks: list[tuple[str, bool, str]] = []
        checks.append(("database reachable", True, "connected"))
        tenants = db.scalar(select(func.count()).select_from(Tenant))
        admins = db.scalar(
            select(func.count())
            .select_from(TenantMembership)
            .where(TenantMembership.role == UserRole.SUPER_ADMIN.value)
        )
        checks.append(("internal tenant exists", (tenants or 0) >= 1, f"tenants={tenants}"))
        checks.append(("super admin exists", (admins or 0) >= 1, f"super_admins={admins}"))
        services = db.scalar(select(func.count()).select_from(Service))
        checks.append(("service taxonomy imported", (services or 0) == 224, f"services={services}"))
        settings_count = db.scalar(select(func.count()).select_from(SystemSetting))
        checks.append(("settings seeded", (settings_count or 0) >= 40, f"settings={settings_count}"))
        caps = db.scalar(select(func.count()).select_from(AgentCapability))
        checks.append(("capability registry seeded", (caps or 0) == 10, f"capabilities={caps}"))
        tools = db.scalar(select(func.count()).select_from(ToolDefinition))
        checks.append(("tool allow-list seeded", (tools or 0) >= 4, f"tools={tools}"))
        checks.append(("audit chain valid", verify_audit_chain(db), "hash-chain verified"))
        checks.append(
            ("password hashing active", verify_password(
                "$argon2id$v=19$m=65536,t=3,p=4$dGVzdA$RdescudvJCsgt3ub+b+dWRWJTmaaJObG",
                "wrong-password") is False, "argon2id verify rejects wrong password")
        )
        ok = True
        print("== Aknja Digital install verification ==")
        for name, passed, detail in checks:
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")
            ok = ok and passed
        audits = db.scalar(select(func.count()).select_from(AuditEvent))
        print(f"  audit events recorded: {audits}")
        return 0 if ok else 1
    finally:
        db.close()


def cmd_demo_seed(_args: argparse.Namespace) -> int:
    """Create clearly-labelled SYNTHETIC demo data (local/staging only).

    Never run against production: the data is fabricated and labelled
    "DEMO" throughout (SRS §12: label demo/test data).
    """
    db = get_session_local()()
    try:
        from uuid import uuid4

        from app.core.config import get_settings
        from app.core.enums import BillingState, LeadStatus, ProviderCategory, UserRole
        from app.modules.crm import service as crm
        from app.modules.delivery import service as delivery
        from app.modules.governance import service as governance
        from app.modules.identity.service import Principal, bootstrap_internal_tenant
        from app.modules.resources import service as quota

        if get_settings().is_production:
            print("ERROR: demo-seed refuses to run in production")
            return 1

        tenant = bootstrap_internal_tenant(db)
        principal = Principal(
            user_id=uuid4(), email="demo@aknja.local", tenant_id=tenant.id,
            role=UserRole.SUPER_ADMIN, client_id=None, session_id=uuid4(), csrf_token="",
        )
        demo_client = crm.create_client(
            db, principal=principal, display_name="DEMO — Sunrise Dental Clinic",
            email="owner@sunrise.example", phone="+91 90000 00000",
        )
        demo_client.notes = "SYNTHETIC DEMO DATA — safe to delete"
        crm.add_contact(
            db, tenant_id=tenant.id, client_id=demo_client.id,
            full_name="DEMO — Dr. Meera", email="meera@sunrise.example", is_primary=True,
        )
        lead = crm.create_lead(
            db, principal=principal, title="DEMO — Clinic booking website",
            source="DIRECT", contact_email="meera@sunrise.example",
            budget_minor=150000, feasibility_score=82,
            description="SYNTHETIC DEMO DATA",
        )
        crm.qualify_lead(db, tenant_id=tenant.id, lead_id=lead.id, to_status=LeadStatus.CONTACTED)
        crm.qualify_lead(db, tenant_id=tenant.id, lead_id=lead.id, to_status=LeadStatus.QUALIFIED, feasibility_score=82)

        project = delivery.create_project(
            db, principal=principal, client_id=demo_client.id,
            name="DEMO — Booking Website", description="SYNTHETIC DEMO DATA",
        )
        delivery.add_requirement(
            db, tenant_id=tenant.id, project_id=project.id,
            title="Online appointment booking", detail="DEMO requirement",
        )
        delivery.add_milestone(
            db, tenant_id=tenant.id, project_id=project.id, title="DEMO — MVP", weight_pct=60, amount_minor=90000
        )
        delivery.add_milestone(
            db, tenant_id=tenant.id, project_id=project.id, title="DEMO — Launch", weight_pct=40, amount_minor=60000
        )
        delivery.create_task(db, tenant_id=tenant.id, project_id=project.id, title="DEMO — Home page")
        delivery.create_staging_preview(
            db, tenant_id=tenant.id, project_id=project.id, url="https://demo-staging.example/preview"
        )

        # A verified free provider so the Quota Centre shows a working example.
        account = quota.register_provider_account(
            db, tenant_id=tenant.id, provider="DEMO — Groq Free",
            billing_state=BillingState.FREE_VERIFIED.value, enabled=True,
        )
        product = quota.register_provider_product(
            db, account=account, product_key="DEMO — free tier requests/day",
            category=ProviderCategory.AI_LLM, allowance=14400,
        )
        quota.record_snapshot(db, product, locally_metered=230)

        approval = governance.create_approval_request(
            db, tenant_id=tenant.id, gate="STAGING_DELIVERABLE",
            title="DEMO — Send staging link to Sunrise Dental",
            payload={"url": "https://demo-staging.example/preview"},
            requested_by_id="demo",
        )
        db.commit()
        print(f"OK demo data created (client, lead, project, provider, approval {approval.id})")
        print("   All rows are labelled DEMO / SYNTHETIC — delete freely.")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aknja", description="Aknja Digital management CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create schema and bootstrap tenant (dev)")
    p_admin = sub.add_parser("create-super-admin", help="create the founder super admin")
    p_admin.add_argument("--email", default=None)
    p_admin.add_argument("--password", default=None)
    p_tax = sub.add_parser("import-taxonomy", help="import source service taxonomy")
    p_tax.add_argument("--md", default=None)
    p_tax.add_argument("--csv", default=None)
    sub.add_parser("seed", help="seed settings, capabilities and tools")
    sub.add_parser("verify-install", help="verify installation evidence")
    sub.add_parser("demo-seed", help="create labelled synthetic demo data (never in production)")
    args = parser.parse_args(argv)

    get_settings()  # load config eagerly for clear failure
    handlers = {
        "init-db": cmd_init_db,
        "create-super-admin": cmd_create_super_admin,
        "import-taxonomy": cmd_import_taxonomy,
        "seed": cmd_seed,
        "verify-install": cmd_verify_install,
        "demo-seed": cmd_demo_seed,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
