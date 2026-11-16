r"""Email ingestion: IMAP UNSEEN -> unified intake (docs/34, T-028).

Architecture decision (founder brief 2026-11-16, verdict in docs/34 §6):
custom-domain addresses on aknja.pp.ua forward into one system Gmail
account via Cloudflare Email Routing (free, receive-only), and the system
polls that single inbox over IMAP with the Gmail app password stored in
the credential hub. Works identically for any other IMAP provider
(Zoho free tier, self-hosted) — host/port live in the credential config.

The IMAP client is injectable so tests run against a stub; `\Seen` is the
poll cursor (idempotent re-poll), and every fetched message goes through
the same governed intake pipeline as manual entry.
"""

from __future__ import annotations

import email
import email.policy
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.governance.service import record_audit
from app.modules.identity.service import Principal, bootstrap_internal_tenant
from app.modules.integrations.models import IntegrationCredential
from app.modules.integrations.service import _decrypt

MAX_MESSAGES_PER_POLL = 25
MAX_AGE_DAYS = 7  # first poll after registration must not ingest ancient mail


def system_principal(db: Session) -> Principal:
    """The internal super admin acts for automated channels (audit trails
    attribute platform actions; intake rows keep created_by NULL)."""
    from app.core.enums import UserRole
    from app.modules.identity.models import TenantMembership, User

    tenant = bootstrap_internal_tenant(db)
    membership = db.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant.id,
            TenantMembership.role == UserRole.SUPER_ADMIN.value,
        )
    )
    user = db.get(User, membership.user_id)
    return Principal(
        user_id=user.id, email=user.email, tenant_id=tenant.id,
        role=UserRole.SUPER_ADMIN, client_id=None, session_id=user.id,
        csrf_token="system",
    )


def _plaintext_body(msg: email.message.EmailMessage) -> str:
    """Best-effort body: prefer text/plain, fall back to the first text part."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                try:
                    return part.get_content()
                except Exception:  # noqa: BLE001, S112 - undecodable part: skip to next
                    continue
        return ""
    try:
        return msg.get_content()
    except Exception:  # noqa: BLE001
        return ""


def _build_content(msg: email.message.EmailMessage) -> str:
    """Header block + body — the intake record shows exactly what arrived."""
    header = (
        f"From: {msg.get('From', '')}\n"
        f"Subject: {msg.get('Subject', '')}\n"
        f"Date: {msg.get('Date', '')}\n"
        f"Message-ID: {msg.get('Message-ID', '')}\n\n"
    )
    body = _plaintext_body(msg).strip()
    return (header + body)[:20000]


def _parse_date(msg: email.message.EmailMessage) -> datetime | None:
    try:
        return email.utils.parsedate_to_datetime(msg.get("Date", ""))
    except (TypeError, ValueError):
        return None


def poll_email_inbox(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    settings: Settings,
    imap_factory: Callable[..., object] | None = None,
    limit: int = MAX_MESSAGES_PER_POLL,
) -> dict:
    """Poll every ACTIVE EMAIL credential; feed unseen mail into intake.

    Returns a per-provider summary. One provider's network failure never
    blocks the others (each polls in its own try/except).
    """
    import imaplib

    from app.modules.intake import service as intake

    rows = db.scalars(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant_id,
            IntegrationCredential.provider_type == "EMAIL",
            IntegrationCredential.status == "ACTIVE",
        )
    ).all()
    summary: dict = {"providers": 0, "fetched": 0, "converted": 0,
                     "needs_review": 0, "rejected": 0, "errors": []}
    if not rows:
        summary["detail"] = "no ACTIVE email credential — nothing to poll"
        return summary

    principal = system_principal(db)
    factory = imap_factory or imaplib.IMAP4_SSL
    cutoff = datetime.now(UTC) - timedelta(days=MAX_AGE_DAYS)
    summary["providers"] = len(rows)

    for row in rows:
        secrets = _decrypt(settings, row.payload_encrypted)
        cfg = row.config or {}
        host = cfg.get("imap_host", "")
        user = secrets.get("username", "")
        password = secrets.get("app_password") or secrets.get("password", "")
        if not (host and user and password):
            summary["errors"].append(f"{row.provider_key}: incomplete credential "
                                     "(needs imap_host + username + app_password)")
            continue
        try:
            client = factory(host, int(cfg.get("imap_port", 993)))
        except Exception as exc:  # noqa: BLE001 - network/SSL failures are expected
            summary["errors"].append(f"{row.provider_key}: connect failed: {exc}")
            record_audit(
                db, tenant_id=tenant_id, actor_type="SYSTEM", actor_id="email_poll",
                action="email_poll.error", resource_type="integration_credential",
                resource_id=str(row.id), payload={"provider": row.provider_key,
                                                  "error": str(exc)[:200]})
            continue
        try:
            typ, _ = client.login(user, password)
            if typ != "OK":
                raise PermissionError("login rejected")
            client.select(cfg.get("folder", "INBOX"), readonly=False)
            typ, data = client.search(None, "UNSEEN")
            if typ != "OK":
                raise ConnectionError("search failed")
            uids = [u for u in (data[0] or b"").split()][:limit]
            for uid in uids:
                typ, msg_data = client.fetch(uid, "(RFC822)")
                if typ != "OK" or not msg_data or msg_data[0] is None:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw, policy=email.policy.default)
                sent = _parse_date(msg)
                if sent is not None and sent.tzinfo is not None and sent < cutoff:
                    client.store(uid, "+FLAGS", "\\Seen")  # too old: skip + mark
                    continue
                sender = email.utils.parseaddr(msg.get("From", ""))[1] or "unknown"
                record = intake.submit_intake_message(
                    db, principal=principal, channel="EMAIL", sender=sender,
                    content=_build_content(msg),
                )
                summary["fetched"] += 1
                if record.status == "CONVERTED":
                    summary["converted"] += 1
                elif record.status == "NEEDS_REVIEW":
                    summary["needs_review"] += 1
                elif record.status == "REJECTED":
                    summary["rejected"] += 1
                client.store(uid, "+FLAGS", "\\Seen")  # cursor: seen = ingested
            client.logout()
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"{row.provider_key}: {exc}")
            record_audit(
                db, tenant_id=tenant_id, actor_type="SYSTEM", actor_id="email_poll",
                action="email_poll.error", resource_type="integration_credential",
                resource_id=str(row.id), payload={"provider": row.provider_key,
                                                  "error": str(exc)[:200]})
        finally:
            try:
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
    return summary
