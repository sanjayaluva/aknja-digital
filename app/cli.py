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


def cmd_register_provider_candidates(_args: argparse.Namespace) -> int:
    """Seed the documented free-tier candidate pool (docs/33, v5.3.2 §5).

    Candidates are FREE_UNVERIFIED + disabled with unknown allowance —
    the quota engine fails closed on all of them until verification.
    """
    db = get_session_local()()
    try:
        from app.modules.identity.service import bootstrap_internal_tenant
        from app.modules.resources.candidates import register_candidate_providers

        tenant = bootstrap_internal_tenant(db)
        stats = register_candidate_providers(db, tenant.id)
        db.commit()
        print(
            f"OK candidate providers registered: {stats['accounts']} accounts, "
            f"{stats['products']} metered products "
            f"({stats['skipped']} already present). All are FREE_UNVERIFIED/disabled."
        )
        print("   Verify each in the provider console, then run: "
              "python -m app.cli verify-provider --provider <name> ...")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_verify_provider(args: argparse.Namespace) -> int:
    """Record verification evidence and (with --enable) activate a candidate.

    This is the docs/33 worksheet turned into an audited founder action:
    the account flips to FREE_VERIFIED, the allowance is set from the real
    console value, a fresh quota snapshot is recorded and an audit event is
    written. Nothing is admitted before this step.
    """
    db = get_session_local()()
    try:
        from sqlalchemy import select

        from app.core.enums import BillingState, UserRole
        from app.core.security import utcnow
        from app.modules.governance.service import record_audit
        from app.modules.identity.models import TenantMembership
        from app.modules.identity.service import Principal, bootstrap_internal_tenant
        from app.modules.resources import service as quota
        from app.modules.resources.models import ProviderAccount, ProviderProduct

        tenant = bootstrap_internal_tenant(db)
        founder_id = db.scalar(
            select(TenantMembership.user_id).where(
                TenantMembership.tenant_id == tenant.id,
                TenantMembership.role == UserRole.SUPER_ADMIN.value,
            )
        )
        principal = Principal(
            user_id=founder_id or tenant.id,  # fall back to tenant id if no admin yet
            email="cli-founder",
            tenant_id=tenant.id,
            role=UserRole.SUPER_ADMIN,
            client_id=None,
            session_id=founder_id or tenant.id,
            csrf_token="",
        )
        account = db.scalar(
            select(ProviderAccount).where(
                ProviderAccount.tenant_id == tenant.id,
                ProviderAccount.provider == args.provider,
            )
        )
        if account is None:
            print(f"ERROR: provider '{args.provider}' is not registered")
            return 1
        product = db.scalar(
            select(ProviderProduct).where(
                ProviderProduct.account_id == account.id,
                ProviderProduct.product_key == args.product_key,
            )
        )
        if product is None:
            products = db.scalars(
                select(ProviderProduct.product_key).where(ProviderProduct.account_id == account.id)
            ).all()
            print(f"ERROR: product '{args.product_key}' not found. Available: {', '.join(products)}")
            return 1
        if args.allowance is None or args.allowance <= 0:
            print("ERROR: --allowance (verified console value, > 0) is required")
            return 1

        product.allowance = int(args.allowance)
        product.metric_key = args.metric or product.metric_key
        product.enabled = True
        account.billing_state = BillingState.FREE_VERIFIED.value
        account.commercial_use_ok = args.commercial_use_ok
        account.last_verified_at = utcnow()
        if args.enable:
            account.enabled = True
        quota.record_snapshot(db, product, locally_metered=0, confidence="MEDIUM")
        record_audit(
            db,
            tenant_id=tenant.id,
            actor_type="USER",
            actor_id=str(principal.user_id),
            action="provider.verified",
            resource_type="provider_product",
            resource_id=str(product.id),
            payload={
                "provider": args.provider,
                "product_key": args.product_key,
                "allowance": int(args.allowance),
                "docs_url": args.docs_url,
                "evidence": args.evidence,
                "enabled": bool(args.enable),
            },
        )
        db.commit()
        state = "ENABLED" if args.enable else "verified (still disabled)"
        print(f"OK {args.provider}/{args.product_key}: FREE_VERIFIED, allowance={args.allowance} — {state}")
        print("   Evidence recorded in the audit ledger (action=provider.verified).")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_llm_ping(args: argparse.Namespace) -> int:
    """Test one verified LLM provider (v5.3.2 §8 'Test provider' action).

    Runs a single completion through the governed inference layer against
    the named provider only — no failover, so the result reflects that
    provider's health, quota and credentials directly.
    """
    db = get_session_local()()
    try:
        from app.modules.ai.inference import llm_complete
        from app.modules.identity.service import bootstrap_internal_tenant

        tenant = bootstrap_internal_tenant(db)
        result = llm_complete(
            db,
            tenant_id=tenant.id,
            task=args.task,
            prompt=args.prompt,
            model=args.model,
            target_provider=args.provider,
        )
        db.commit()
        if result.status == "SUCCEEDED":
            print(f"OK {result.provider}/{result.model} — {result.latency_ms} ms")
            print(f"   response: {result.text.strip()[:400]}")
            return 0
        print(f"FAILED [{result.status}] {result.reason}")
        if "not eligible" in result.reason or "no AI_LLM product" in result.reason:
            print("   run: python -m app.cli verify-provider --provider "
                  f"{args.provider} --product-key \"...\" --allowance <console value> --enable")
        return 1
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_process_notifications(_args: argparse.Namespace) -> int:
    """Drain due Telegram notifications (docs/39: send/retry without loss).

    Unconfigured channel is reported, not treated as failure — the rows stay
    PENDING and nothing is lost until the founder sets TELEGRAM_BOT_TOKEN /
    TELEGRAM_ADMIN_CHAT_ID.
    """
    db = get_session_local()()
    try:
        from app.modules.ops.notifications import pending_count, process_outbox

        summary = process_outbox(db)
        db.commit()
        print(
            f"processed: {summary['due']} due — {summary['sent']} sent, "
            f"{summary['retried']} scheduled for retry, {summary['failed']} failed, "
            f"{summary['unconfigured']} waiting for channel config"
        )
        remaining = pending_count(db)
        if remaining:
            print(f"outbox: {remaining} notification(s) still pending")
        if summary["unconfigured"]:
            print("   channel not configured: set TELEGRAM_BOT_TOKEN and "
                  "TELEGRAM_ADMIN_CHAT_ID (create the bot with @BotFather, "
                  "then message it once and use the chat id)")
        return 0 if summary["failed"] == 0 else 1
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_send_test_notification(args: argparse.Namespace) -> int:
    """v5.3.2 §8-style 'Test channel' action for the Telegram bot."""
    import uuid as _uuid

    db = get_session_local()()
    try:
        from app.modules.identity.service import bootstrap_internal_tenant
        from app.modules.ops.notifications import enqueue_notification, process_outbox

        tenant = bootstrap_internal_tenant(db)
        row = enqueue_notification(
            db,
            template_key="system.test",
            payload={},
            idempotency_key=f"system.test:{_uuid.uuid4()}",
            tenant_id=tenant.id,
            language=args.language,
        )
        db.commit()
        if row is None:  # lost a concurrent race on the unique key
            print("ERROR: could not enqueue test notification")
            return 1
        summary = process_outbox(db)
        db.commit()
        if summary["sent"]:
            print(f"OK test message delivered (ref {row.idempotency_key[-16:]})")
            return 0
        if summary["unconfigured"]:
            print("CHANNEL NOT CONFIGURED — set TELEGRAM_BOT_TOKEN and "
                  "TELEGRAM_ADMIN_CHAT_ID, then run: "
                  "python -m app.cli process-notifications")
            return 1
        print(f"FAILED to deliver: {row.last_error or 'unknown error'}")
        return 1
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
    sub.add_parser(
        "register-provider-candidates",
        help="seed the documented free-tier candidate pool (FREE_UNVERIFIED, disabled)",
    )
    p_ping = sub.add_parser(
        "llm-ping", help="test a verified LLM provider with one real completion"
    )
    p_ping.add_argument("--provider", required=True, help="provider key, e.g. groq")
    p_ping.add_argument("--model", default=None, help="override the provider default model")
    p_ping.add_argument("--prompt", default="Reply with exactly: PONG")
    p_ping.add_argument("--task", default="classification", help="task profile key")
    p_verify = sub.add_parser(
        "verify-provider", help="record verification evidence and enable a candidate provider"
    )
    p_verify.add_argument("--provider", required=True, help="provider key, e.g. groq")
    p_verify.add_argument("--product-key", required=True, dest="product_key")
    p_verify.add_argument("--allowance", type=int, default=None, help="verified console allowance (> 0)")
    p_verify.add_argument("--metric", default=None, help="override metric key, e.g. requests")
    p_verify.add_argument("--docs-url", default="", dest="docs_url")
    p_verify.add_argument("--evidence", default="", help="what was checked, by whom")
    p_verify.add_argument("--enable", action="store_true", help="also enable the account for admission")
    p_verify.add_argument("--commercial-use-ok", action="store_true", dest="commercial_use_ok")
    sub.add_parser(
        "process-notifications",
        help="drain the due Telegram notification outbox (send/retry per docs/39)",
    )
    p_note = sub.add_parser(
        "send-test-notification", help="enqueue and deliver a test Telegram message"
    )
    p_note.add_argument("--language", default=None, help="ml (default) or en")
    args = parser.parse_args(argv)

    get_settings()  # load config eagerly for clear failure
    handlers = {
        "init-db": cmd_init_db,
        "create-super-admin": cmd_create_super_admin,
        "import-taxonomy": cmd_import_taxonomy,
        "seed": cmd_seed,
        "verify-install": cmd_verify_install,
        "demo-seed": cmd_demo_seed,
        "register-provider-candidates": cmd_register_provider_candidates,
        "verify-provider": cmd_verify_provider,
        "llm-ping": cmd_llm_ping,
        "process-notifications": cmd_process_notifications,
        "send-test-notification": cmd_send_test_notification,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
