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
import uuid
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


def cmd_prepare_service_delivery(args: argparse.Namespace) -> int:
    """Stamp delivery blueprints on every catalog service (T-026).

    Optionally promote named services to AVAILABLE_AI_ASSISTED / LIMITED with
    the six readiness evidence keys recorded as verified — the source note
    must state what was actually verified (tool access, blueprint, RBAC,
    privacy gates, quota, quality floors).
    """
    db = get_session_local()()
    try:
        from sqlalchemy import select

        from app.core.enums import UserRole
        from app.modules.catalog.models import Service
        from app.modules.catalog.service import (
            promote_deliverable_service,
            stamp_delivery_templates,
        )
        from app.modules.identity.service import Principal, bootstrap_internal_tenant

        tenant = bootstrap_internal_tenant(db)
        # promotion evidence needs a REAL verified_by user (FK); use the
        # tenant's actual super admin rather than a synthetic id
        from app.modules.identity.models import TenantMembership, User

        admin = db.scalars(
            select(User).join(TenantMembership, TenantMembership.user_id == User.id)
            .where(
                TenantMembership.tenant_id == tenant.id,
                TenantMembership.role == UserRole.SUPER_ADMIN.value,
            ).order_by(User.created_at)
        ).first()
        if admin is None:
            print("ERROR: no super admin user exists for the internal tenant")
            return 1
        principal = Principal(
            user_id=admin.id, email=admin.email, tenant_id=tenant.id,
            role=UserRole.SUPER_ADMIN, client_id=None, session_id=admin.id,
            csrf_token="",
        )
        stamped = stamp_delivery_templates(db, tenant.id)
        db.commit()
        print(f"OK delivery templates stamped on {stamped} service items")
        if args.promote:
            if not args.note:
                print("ERROR: --promote requires a truthful --note for the evidence record")
                return 1
            for name in [n.strip() for n in args.promote.split(",") if n.strip()]:
                matches = db.scalars(
                    select(Service).where(
                        Service.tenant_id == tenant.id, Service.name == name
                    )
                ).all()
                if not matches:
                    print(f"ERROR: no service named {name!r}")
                    return 1
                if len(matches) > 1:
                    print(f"ERROR: service name {name!r} is ambiguous")
                    return 1
                service = promote_deliverable_service(
                    db, principal=principal, service_id=matches[0].id,
                    source_note=args.note,
                )
                db.commit()
                print(f"OK promoted {service.name!r}: {service.availability} / "
                      f"{service.readiness} / {service.execution_mode}")
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

    The operator running a health check IS fresh quota evidence: the latest
    snapshot is re-observed first (last locally-metered usage carried over),
    otherwise a >6h-old snapshot would fail-closed the very check meant to
    prove the provider healthy (observed live 2026-11-16: every provider
    gated as 'stale quota snapshot' and the ping could never self-heal).
    """
    db = get_session_local()()
    try:
        from sqlalchemy import select

        from app.core.security import utcnow
        from app.modules.ai.inference import _target_product, llm_complete
        from app.modules.identity.service import bootstrap_internal_tenant
        from app.modules.resources import service as quota
        from app.modules.resources.models import QuotaSnapshot

        tenant = bootstrap_internal_tenant(db)
        pair = _target_product(db, tenant.id, args.provider)
        if pair is not None:
            last_snap = db.scalar(
                select(QuotaSnapshot).where(
                    QuotaSnapshot.provider_product_id == pair[0].id
                ).order_by(QuotaSnapshot.observed_at.desc()).limit(1)
            )
            # daily metrics reset at UTC midnight: carry yesterday's usage
            # across the boundary and every provider fail-closes at a
            # hard-stop that has already reset (observed live 2026-11-16)
            same_day = (
                last_snap is not None
                and last_snap.observed_at.date() == utcnow().date()
            )
            quota.record_snapshot(
                db, pair[0],
                provider_reported=last_snap.effective_usage if same_day else 0,
                confidence="MEDIUM",
            )
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



def cmd_poll_email(args: argparse.Namespace) -> int:
    """Poll ACTIVE email credentials and feed unseen mail into intake (T-028).

    Designed for a systemd timer; a run without any ACTIVE email credential
    is a no-op (exit 0) so the timer can be installed before Gmail exists.
    """
    db = get_session_local()()
    try:
        from app.modules.identity.service import bootstrap_internal_tenant
        from app.modules.integrations.email_poll import poll_email_inbox

        tenant = bootstrap_internal_tenant(db)
        summary = poll_email_inbox(db, tenant_id=tenant.id, settings=get_settings())
        db.commit()
        print(f"email poll: providers={summary['providers']} "
              f"fetched={summary['fetched']} converted={summary['converted']} "
              f"needs_review={summary['needs_review']} rejected={summary['rejected']}")
        for err in summary.get("errors", []):
            print(f"  ! {err}")
        return 0
    finally:
        db.close()


def cmd_telegram_set_webhook(args: argparse.Namespace) -> int:
    """Point an ACTIVE telegram bot credential at our public webhook (T-029).

    Generates and stores a webhook secret when absent (rotating it is just
    re-running this command), then calls Telegram setWebhook.
    """
    db = get_session_local()()
    try:
        import uuid as _uuid

        import httpx
        from sqlalchemy import select

        from app.modules.identity.service import Principal, bootstrap_internal_tenant
        from app.modules.integrations import service as integrations
        from app.modules.integrations.models import IntegrationCredential

        tenant = bootstrap_internal_tenant(db)
        row = db.scalar(select(IntegrationCredential).where(
            IntegrationCredential.provider_key == args.provider,
            IntegrationCredential.provider_type == "MESSAGING",
            IntegrationCredential.tenant_id == tenant.id))
        if row is None or row.status != "ACTIVE":
            print(f"no ACTIVE MESSAGING credential '{args.provider}' — "
                  "register and activate it in Admin > Integrations first")
            return 1
        settings = get_settings()
        secrets = integrations._decrypt(settings, row.payload_encrypted)
        if not secrets.get("webhook_secret"):
            secrets["webhook_secret"] = _uuid.uuid4().hex
            row.payload_encrypted = integrations._encrypt(settings, secrets)
            db.flush()
        base = (row.config or {}).get("public_base_url", "https://aknja.pp.ua")
        url = f"{base.rstrip('/')}/hooks/telegram/{args.provider}"
        token = secrets.get("bot_token", "")
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={"url": url, "secret_token": secrets["webhook_secret"],
                  "allowed_updates": ["message"]},
            timeout=30)
        ok = resp.status_code == 200 and resp.json().get("ok")
        db.commit()
        print(f"setWebhook -> {url}: {'OK' if ok else resp.text[:200]}")
        print("inbound messages will now flow into Admin > Intake "
              "(classification runs through the governed pool)")
        return 0 if ok else 1
    finally:
        db.close()


def cmd_run_llm_benchmark(args: argparse.Namespace) -> int:
    """Run the v5.3.2 §6 quality benchmark against one provider (no failover).

    Exit 0 only if every selected task meets its quality floor; a failed run
    records a FAILED benchmark row which the inference gate then enforces
    (the provider stops being eligible for the failed tasks until re-run).
    """
    db = get_session_local()()
    try:
        from app.core.errors import ConflictError
        from app.modules.ai.benchmark import run_benchmark
        from app.modules.identity.service import bootstrap_internal_tenant

        tenant = bootstrap_internal_tenant(db)
        tasks = [t.strip() for t in args.tasks.split(",")] if args.tasks else None
        languages = [l.strip() for l in args.languages.split(",")] if args.languages else None
        card = run_benchmark(
            db, tenant_id=tenant.id, provider=args.provider,
            tasks=tasks, languages=languages,
        )
        db.commit()
        print(f"benchmark {card['benchmark_version']} — provider '{card['provider']}' "
              f"({card['scenarios']} scenarios, tasks: {', '.join(card['tasks'])})")
        for task, entry in card["per_task"].items():
            verdict = "PASS" if entry["passed"] else "FAIL"
            print(f"  {task:<16} {entry['score']:.0%} (floor {entry['floor']:.0%}) "
                  f"{verdict}  [{entry['scenarios']} scenarios]")
        for lang, entry in card["per_language"].items():
            print(f"  lang {lang}: {entry['score']:.0%} over {entry['scenarios']} scenarios")
        print(f"overall: {card['overall_score']:.0%} — "
              f"{'PASSED' if card['passed'] else 'FAILED'} "
              f"(record {card['record_id']})")
        if card.get("inconclusive"):
            print(f"NOTE: run recorded as INCONCLUSIVE ({card.get('provider_errors', 0)}/"
                  f"{card['scenarios']} scenarios were provider errors — availability, "
                  "not quality). The quality gate keeps the previous conclusive verdict.")
        elif not card["passed"]:
            print("the inference layer now skips this provider for the failed tasks "
                  "until a passing re-run (v5.3.2 §6)")
        return 0 if card["passed"] else 1
    except ConflictError as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_backup_create(args: argparse.Namespace) -> int:
    """pg_dump the primary database + manifest + BackupRecord (v5.3.2 §5A)."""
    db = get_session_local()()
    try:
        from app.modules.ops.backup import create_backup

        result = create_backup(db, backup_dir=args.dir)
        print(f"backup created: {result.record.storage_key}")
        print(f"  artifact : {result.artifact}")
        print(f"  sha256   : {result.sha256}")
        print(f"  size     : {result.size_bytes / 1_048_576:.2f} MB")
        print(f"  rows     : {sum(result.table_counts.values())} across "
              f"{len(result.table_counts)} tables")
        print(f"  duration : {result.duration_ms} ms")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_backup_verify(args: argparse.Namespace) -> int:
    """Checksum-verify the newest (or named) backup; optional freshness SLO."""
    db = get_session_local()()
    try:
        from app.modules.ops.backup import _latest_records, verify_backup

        storage_key = args.backup
        if storage_key is None:
            latest = _latest_records(db, 1)
            if not latest:
                print("no backups recorded — run 'aknja backup create' first")
                return 1
            storage_key = latest[0].storage_key
        result = verify_backup(args.dir, storage_key, max_age_hours=args.max_age_hours)
        status = "OK" if result.ok else "FAIL"
        age = f" age={result.age_hours:.1f}h" if result.age_hours is not None else ""
        print(f"backup verify [{status}] {storage_key}: {result.reason}{age}")
        return 0 if result.ok else 1
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_backup_drill(args: argparse.Namespace) -> int:
    """Restore a backup into an isolated scratch DB and verify it (docs/22)."""
    db = get_session_local()()
    try:
        from app.modules.ops.backup import run_restore_drill

        result = run_restore_drill(db, storage_key=args.backup, backup_dir=args.dir,
                                   drop_target=not args.keep_target)
        status = "PASSED" if result.ok else "FAILED"
        checks = (f"counts={'ok' if result.counts_match else 'MISMATCH'} "
                  f"schema={'ok' if result.alembic_match else 'MISMATCH'} "
                  f"audit_chain={'ok' if result.chain_valid else 'BROKEN'}")
        print(f"restore drill [{status}] {result.storage_key} "
              f"({result.duration_ms} ms, target {result.target_db})")
        print(f"  {checks}")
        if result.reason:
            print(f"  reason: {result.reason}")
        return 0 if result.ok else 1
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_backup_prune(args: argparse.Namespace) -> int:
    """Delete old artifacts, never the last known-good backup (docs/22)."""
    db = get_session_local()()
    try:
        from app.modules.ops.backup import prune_backups

        result = prune_backups(db, keep_last=args.keep, backup_dir=args.dir)
        if result.refused_reason:
            print(f"prune refused: {result.refused_reason}")
            return 1
        print(f"pruned {len(result.removed)} backup(s); kept: {', '.join(result.kept) or 'none'}")
        for key in result.removed:
            print(f"  removed: {key}")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_backup_push(args: argparse.Namespace) -> int:
    """Upload a backup artifact + manifest offsite (docs/22 §5A, R2/S3)."""
    db = get_session_local()()
    try:
        from app.core.config import get_settings
        from app.modules.ops.backup import _latest_records
        from app.modules.ops.models import BackupRecord
        from app.modules.ops.offsite import offsite_target, push_backup_offsite

        if offsite_target() is None:
            print("offsite storage NOT CONFIGURED — set OBJECT_STORAGE_ENDPOINT, "
                  "OBJECT_STORAGE_BUCKET, OBJECT_STORAGE_ACCESS_KEY_ID and "
                  "OBJECT_STORAGE_SECRET_ACCESS_KEY (docs/22 §5A)")
            return 1
        if args.id:
            record = db.get(BackupRecord, args.id)
            if record is None:
                print(f"ERROR: no backup record with id {args.id}")
                return 1
        else:
            pending = [
                r for r in _latest_records(db, 50) if not r.offsite_key
            ] or _latest_records(db, 1)
            record = pending[0]
        directory = Path(args.dir) if args.dir else Path(get_settings().backup_dir)
        artifact = directory / record.storage_key
        if not artifact.is_file():
            print(f"ERROR: artifact missing locally: {artifact}")
            return 1
        key = push_backup_offsite(db, record, artifact=artifact)
        print(f"offsite push OK {record.storage_key}")
        print(f"  remote key: {key}")
        print(f"  size      : {record.size_bytes / 1_048_576:.2f} MB")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_backup_offsite_drill(args: argparse.Namespace) -> int:
    """Download an offsite backup, verify its checksum, restore-drill it."""
    import tempfile

    db = get_session_local()()
    try:
        from sqlalchemy import select

        from app.modules.ops.backup import run_restore_drill
        from app.modules.ops.models import BackupRecord
        from app.modules.ops.offsite import pull_backup_offsite

        query = select(BackupRecord).where(BackupRecord.offsite_key.is_not(None))
        if args.backup:
            query = query.where(BackupRecord.storage_key == args.backup)
        else:
            query = query.order_by(BackupRecord.created_at.desc())
        record = db.scalars(query.order_by(BackupRecord.created_at.desc())).first()
        if record is None:
            print("no offsite backups recorded — run 'aknja backup push' first")
            return 1
        with tempfile.TemporaryDirectory(prefix="aknja-offsite-") as tmp:
            dest = Path(tmp)
            _artifact, remote_manifest = pull_backup_offsite(db, record, dest_dir=dest)
            print(f"offsite download OK {record.storage_key} "
                  f"(checksum verified, manifest={'yes' if remote_manifest else 'absent'})")
            result = run_restore_drill(
                db, storage_key=record.storage_key, backup_dir=dest,
                drop_target=not args.keep_target,
            )
        status = "PASSED" if result.ok else "FAILED"
        checks = (f"counts={'ok' if result.counts_match else 'MISMATCH'} "
                  f"schema={'ok' if result.alembic_match else 'MISMATCH'} "
                  f"audit_chain={'ok' if result.chain_valid else 'BROKEN'}")
        print(f"offsite restore drill [{status}] {result.storage_key} "
              f"({result.duration_ms} ms, target {result.target_db})")
        print(f"  {checks}")
        if result.reason:
            print(f"  reason: {result.reason}")
        return 0 if result.ok else 1
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_monitor_run(_args: argparse.Namespace) -> int:
    """Run all health checks; manage incidents; execute capped safe recovery."""
    db = get_session_local()()
    try:
        from app.modules.ops.monitor import run_monitor

        summary = run_monitor(db)
        for name, result in summary.items():
            state = "OK" if result["ok"] else f"FAIL/{result['severity']}"
            line = f"{name}: {state}"
            if result["incident_id"]:
                line += f" incident={result['incident_id']}"
            if result["recovery"]:
                line += f" recovery={result['recovery']}"
            print(line)
        failures = sum(1 for r in summary.values() if not r["ok"])
        print(f"{len(summary) - failures}/{len(summary)} checks healthy")
        return 0 if failures == 0 else 1
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_monitor_diagnose(args: argparse.Namespace) -> int:
    """AI diagnosis of one incident through the governed pool (fail-closed)."""
    db = get_session_local()()
    try:
        from app.modules.ops.monitor import diagnose_incident

        result = diagnose_incident(db, uuid.UUID(args.incident_id))
        if result["status"] != "SUCCEEDED":
            print(f"diagnosis not produced ({result['status']}): {result.get('reason', '')}")
            return 1
        print(result["diagnosis"])
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_maintenance_on(args: argparse.Namespace) -> int:
    """Enable the write freeze (v5.3.2 §5A controlled promotion / v5.3.1 L141)."""
    db = get_session_local()()
    try:
        from app.modules.ops.maintenance import set_maintenance_mode

        changed, previous = set_maintenance_mode(
            db, enabled=True, reason=args.reason, actor="CLI:founder"
        )
        if not changed:
            print("maintenance mode already ON — no change")
        else:
            print(f"maintenance mode ON (was {'ON' if previous else 'OFF'})"
                  + (f" — {args.reason}" if args.reason else ""))
            print("mutating requests now get 503 + Retry-After; reads and /healthz stay up")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_maintenance_off(_args: argparse.Namespace) -> int:
    """Disable the write freeze."""
    db = get_session_local()()
    try:
        from app.modules.ops.maintenance import set_maintenance_mode

        changed, previous = set_maintenance_mode(db, enabled=False, actor="CLI:founder")
        if not changed:
            print("maintenance mode already OFF — no change")
        else:
            print(f"maintenance mode OFF (was {'ON' if previous else 'OFF'}); writes re-enabled")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


def cmd_maintenance_status(_args: argparse.Namespace) -> int:
    """Show the write-freeze state and the newest backup freshness (H5/H6)."""
    db = get_session_local()()
    try:
        from app.modules.ops.backup import latest_backup_status
        from app.modules.ops.maintenance import is_maintenance_enabled, maintenance_reason

        state = "ON" if is_maintenance_enabled() else "OFF"
        reason = maintenance_reason()
        print(f"maintenance mode: {state}" + (f" — {reason}" if reason else ""))
        backup = latest_backup_status(db)
        if backup is None:
            print("backups: none recorded — run 'aknja backup create'")
        else:
            print(f"latest backup  : {backup.storage_key} — "
                  f"{'OK' if backup.ok else 'PROBLEM: ' + backup.reason}")
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
    p_deliv = sub.add_parser(
        "prepare-service-delivery",
        help="stamp delivery blueprints on catalog services; optionally promote named items (T-026)",
    )
    p_deliv.add_argument("--promote", default=None,
                         help="comma-separated exact service names to promote to AVAILABLE_AI_ASSISTED/LIMITED")
    p_deliv.add_argument("--note", default=None,
                         help="truthful source note recorded on the promotion evidence (required with --promote)")
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
    # --- backup & maintenance (v5.3.2 §5A, docs/22) — nested subcommands ---
    p_backup = sub.add_parser("backup", help="backup/verify/drill/prune (v5.3.2 §5A, docs/22)")
    backup_sub = p_backup.add_subparsers(dest="subcommand", required=True)
    p_bk_dir = argparse.ArgumentParser(add_help=False)
    p_bk_dir.add_argument("--dir", default=None, help="backup directory (default: settings.backup_dir)")
    backup_sub.add_parser("create", parents=[p_bk_dir],
                           help="pg_dump the primary DB + manifest + record")
    p_bv = backup_sub.add_parser("verify", parents=[p_bk_dir],
                                 help="checksum-verify the newest (or named) backup")
    p_bv.add_argument("backup", nargs="?", default=None, help="storage key (default: newest)")
    p_bv.add_argument("--max-age-hours", type=float, default=None, dest="max_age_hours")
    p_bd = backup_sub.add_parser("drill", parents=[p_bk_dir],
                                 help="restore into an isolated scratch DB and verify (docs/22)")
    p_bd.add_argument("backup", nargs="?", default=None, help="storage key (default: newest)")
    p_bd.add_argument("--keep-target", action="store_true", dest="keep_target",
                      help="keep the scratch database after the drill")
    p_bp = backup_sub.add_parser("prune", parents=[p_bk_dir],
                                 help="delete old artifacts, never the last known-good backup")
    p_bp.add_argument("--keep", type=int, default=5, help="verified backups to retain (default 5)")
    p_bpush = backup_sub.add_parser("push", parents=[p_bk_dir],
                                    help="upload a backup + manifest offsite (R2/S3, docs/22 §5A)")
    p_bpush.add_argument("--id", default=None, help="backup record UUID (default: newest without an offsite copy)")
    p_bod = backup_sub.add_parser("offsite-drill", parents=[p_bk_dir],
                                  help="download the offsite copy, verify checksum, restore drill")
    p_bod.add_argument("backup", nargs="?", default=None, help="storage key (default: newest offsite)")
    p_bod.add_argument("--keep-target", action="store_true", dest="keep_target",
                       help="keep the scratch database after the drill")

    p_maint = sub.add_parser("maintenance", help="controlled write freeze (v5.3.2 §5A)")
    maint_sub = p_maint.add_subparsers(dest="subcommand", required=True)
    p_maint_on = maint_sub.add_parser("on", help="enable write freeze: 503 on writes, reads stay up")
    p_maint_on.add_argument("--reason", default="", help="why (promotion, quota exhaustion, ...)")
    maint_sub.add_parser("off", help="disable write freeze")
    maint_sub.add_parser("status", help="show freeze state + newest backup freshness")
    # --- incident monitor (docs/20, Phase 8) — nested subcommands ---
    p_mon = sub.add_parser("monitor", help="health checks -> incidents -> safe recovery (docs/20)")
    mon_sub = p_mon.add_subparsers(dest="subcommand", required=True)
    mon_sub.add_parser("run", help="run all checks, manage incidents, capped allow-listed recovery")
    p_mon_diag = mon_sub.add_parser("diagnose", help="AI diagnosis of one incident (fail-closed)")
    p_mon_diag.add_argument("incident_id", help="incident UUID")
    sub.add_parser(
        "process-notifications",
        help="drain the due Telegram notification outbox (send/retry per docs/39)",
    )
    p_note = sub.add_parser(
        "send-test-notification", help="enqueue and deliver a test Telegram message"
    )
    p_note.add_argument("--language", default=None, help="ml (default) or en")
    p_bench = sub.add_parser(
        "run-llm-benchmark",
        help="run the v5.3.2 §6 quality benchmark (ml/en/hi/ta) against one provider",
    )
    p_bench.add_argument("--provider", required=True, help="provider key, e.g. groq")
    p_bench.add_argument("--tasks", default=None,
                         help="comma-separated task profiles (default: all seven)")
    p_bench.add_argument("--languages", default=None,
                         help="comma-separated languages (default: ml,en,hi,ta)")
    p_email = subparsers.add_parser(
        "poll-email",
        help="poll ACTIVE email credentials (IMAP) into the intake pipeline",
    )
    p_email.add_argument("--provider", default=None,
                         help="reserved: poll a single provider key (default: all)")
    p_hook = subparsers.add_parser(
        "telegram-set-webhook",
        help="point an ACTIVE telegram bot credential at /hooks/telegram/<key>",
    )
    p_hook.add_argument("--provider", default="telegram_bot",
                        help="credential provider_key (default: telegram_bot)")
    args = parser.parse_args(argv)

    get_settings()  # load config eagerly for clear failure
    handlers = {
        "init-db": cmd_init_db,
        "create-super-admin": cmd_create_super_admin,
        "import-taxonomy": cmd_import_taxonomy,
        "prepare-service-delivery": cmd_prepare_service_delivery,
        "seed": cmd_seed,
        "verify-install": cmd_verify_install,
        "demo-seed": cmd_demo_seed,
        "register-provider-candidates": cmd_register_provider_candidates,
        "verify-provider": cmd_verify_provider,
        "llm-ping": cmd_llm_ping,
        "process-notifications": cmd_process_notifications,
        "send-test-notification": cmd_send_test_notification,
        "run-llm-benchmark": cmd_run_llm_benchmark,
        "poll-email": cmd_poll_email,
        "telegram-set-webhook": cmd_telegram_set_webhook,
        "backup create": cmd_backup_create,
        "backup verify": cmd_backup_verify,
        "backup drill": cmd_backup_drill,
        "backup prune": cmd_backup_prune,
        "backup push": cmd_backup_push,
        "backup offsite-drill": cmd_backup_offsite_drill,
        "maintenance on": cmd_maintenance_on,
        "maintenance off": cmd_maintenance_off,
        "maintenance status": cmd_maintenance_status,
        "monitor run": cmd_monitor_run,
        "monitor diagnose": cmd_monitor_diagnose,
    }
    if args.command in ("backup", "maintenance", "monitor"):
        return handlers[f"{args.command} {args.subcommand}"](args)
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
