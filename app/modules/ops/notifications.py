"""Admin notification outbox — Telegram channel (docs/39 reliability rules).

Semantics required by docs/39 and implemented here:
- durable outbox records with a UNIQUE idempotency key (duplicate prevention:
  a business event enqueues exactly once; re-enqueue returns the existing row);
- retry with exponential backoff, honoring Telegram's `retry_after` on 429;
- terminal failure on definitive rejections (400 chat not found, 403 blocked
  bot) — no retry, acceptance is known-negative;
- uncertain acceptance (429/5xx/network): the row stays PENDING for a later
  attempt. Because a Telegram send is not idempotent, an uncertain timeout can
  produce a provider-side duplicate; every rendered body therefore carries a
  `· ref <key>` footer so duplicates are identifiable and reconcilable;
- channel not configured (token/chat unset): rows stay PENDING, attempts stay
  0 — nothing is lost, delivery happens once the founder configures the bot.

A model response never lands here directly: hooks enqueue from audited
platform events (approval requested, quota hard-stop, AI run parked for
review). The outbox row IS the delivery record; no per-send audit noise.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError
from app.core.security import utcnow
from app.modules.ops.models import NotificationOutbox
from app.modules.ops.settings_service import get_setting

MAX_ATTEMPTS = 6
BASE_BACKOFF_S = 60
MAX_BACKOFF_S = 3600
MAX_RETRY_AFTER_S = 86_400
TELEGRAM_API = "https://api.telegram.org"

# template_key -> language -> body with {field} placeholders.
TEMPLATES: dict[str, dict[str, str]] = {
    "approval.requested": {
        "ml": ("അംഗീകാരം ആവശ്യമാണ്: {title}\n"
               "ഗേറ്റ്: {gate}\nകാലഹരിപ്പ്: {expires_at}\nനോൺസ്: {nonce}"),
        "en": ("Approval needed: {title}\n"
               "Gate: {gate}\nExpires: {expires_at}\nNonce: {nonce}"),
    },
    "quota.hard_stop": {
        "ml": "ക്വോട്ട മുന്നറിയിപ്പ്: {product_key} — {used_pct:g}% ഉപയോഗം "
              "(ഹാർഡ്-സ്റ്റോപ്പ് {cap_pct:g}%). പുതിയ ഉപയോഗം തടഞ്ഞു.",
        "en": "Quota alert: {product_key} — {used_pct:g}% used "
              "(hard-stop {cap_pct:g}%). New usage blocked.",
    },
    "run.blocked": {
        "ml": "AI റൺ തടഞ്ഞു: {objective}\nകാരണം: {reason}\nറൺ: {run_id}",
        "en": "AI run parked for review: {objective}\nReason: {reason}\nRun: {run_id}",
    },
    "benchmark.failed": {
        "ml": "ക്വാളിറ്റി ബെഞ്ച്മാർക്ക് പരാജയപ്പെട്ടു: {provider}\nപരാജയപ്പെട്ട ടാസ്ക്കുകൾ: "
              "{failed_tasks}\nസ്കോർ: {overall_score}",
        "en": "Quality benchmark FAILED: {provider}\nFailed tasks: {failed_tasks}\n"
              "Score: {overall_score}",
    },
    "system.test": {
        "ml": "ടെസ്റ്റ് സന്ദേശം — ടെലിഗ്രാം ചാനൽ സജ്ജമാണ്.",
        "en": "Test message — the Telegram channel is configured and working.",
    },
    "backup.completed": {
        "ml": "ബാക്കപ്പ് പൂർത്തിയായി: {storage_key} ({size_mb:.1f} MB)",
        "en": "Backup completed: {storage_key} ({size_mb:.1f} MB)",
    },
    "backup.drill_completed": {
        "ml": "റിസ്റ്റോർ ഡ്രിൽ വിജയിച്ചു: {storage_key} — {duration_s:.1f} സെക്കൻഡ്",
        "en": "Restore drill PASSED: {storage_key} — {duration_s:.1f}s",
    },
    "backup.drill_failed": {
        "ml": "റിസ്റ്റോർ ഡ്രിൽ പരാജയപ്പെട്ടു: {storage_key} — {reason}",
        "en": "Restore drill FAILED: {storage_key} — {reason}",
    },
    "maintenance.activated": {
        "ml": "മെയിന്റനൻസ് മോഡ് ഓണാക്കി (റൈറ്റ് ഫ്രീസ്): {reason}",
        "en": "Maintenance mode ON (write freeze): {reason}",
    },
    "maintenance.deactivated": {
        "ml": "മെയിന്റനൻസ് മോഡ് ഓഫാക്കി: {reason}",
        "en": "Maintenance mode OFF: {reason}",
    },
    "incident.opened": {
        "ml": "സംഭവം തുറന്നു: {check} — {severity}\n{detail}",
        "en": "Incident OPENED: {check} — {severity}\n{detail}",
    },
    "incident.resolved": {
        "ml": "സംഭവം പരിഹരിച്ചു: {check} — {title}",
        "en": "Incident RESOLVED: {check} — {title}",
    },
}


def render_body(template_key: str, language: str, payload: dict) -> str:
    """Render a template; unknown keys or fields fail loudly at enqueue time."""
    languages = TEMPLATES.get(template_key)
    if languages is None:
        raise ConflictError(f"Unknown notification template '{template_key}'")
    template = languages.get(language) or languages["ml"]
    try:
        return template.format(**payload)
    except KeyError as exc:
        raise ConflictError(
            f"Template '{template_key}' missing field {exc} in payload",
            details={"template": template_key, "field": str(exc)},
        ) from exc


def enqueue_notification(
    db: Session,
    *,
    template_key: str,
    payload: dict,
    idempotency_key: str,
    tenant_id: uuid.UUID | None = None,
    channel: str = "telegram",
    language: str | None = None,
    approval_request_id: uuid.UUID | None = None,
    settings=None,
) -> NotificationOutbox | None:
    """Idempotent enqueue: the same key always returns the existing row.

    Returns None only when a concurrent transaction (e.g. another worker
    hitting the same quota hard-stop) won the unique-index race and has not
    committed yet — the alert is already on its way, so skipping is correct.
    """
    existing = db.scalar(
        select(NotificationOutbox).where(NotificationOutbox.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing
    cfg = settings or get_settings()
    resolved_language = language or str(get_setting(db, "default_admin_language", "ml") or "ml")
    body = render_body(template_key, resolved_language, payload)
    body += f"\n· ref {idempotency_key[-16:]}"  # provider-side duplicate marker
    row = NotificationOutbox(
        tenant_id=tenant_id,
        channel=channel,
        recipient=cfg.telegram_admin_chat_id or "",
        template_key=template_key,
        language=resolved_language,
        payload=payload,
        body=body,
        idempotency_key=idempotency_key,
        approval_request_id=approval_request_id,
    )
    try:
        # SAVEPOINT: a lost unique-index race must not poison the caller's
        # transaction (quota admissions run concurrently against one product).
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        winner = db.scalar(
            select(NotificationOutbox).where(
                NotificationOutbox.idempotency_key == idempotency_key
            )
        )
        return winner
    return row


def notify_admin(
    db: Session,
    *,
    template_key: str,
    payload: dict,
    idempotency_key: str,
    tenant_id: uuid.UUID | None = None,
    approval_request_id: uuid.UUID | None = None,
) -> NotificationOutbox | None:
    """Convenience hook for platform events -> founder Telegram channel."""
    return enqueue_notification(
        db,
        template_key=template_key,
        payload=payload,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        approval_request_id=approval_request_id,
    )


def _next_delay_s(attempts: int, retry_after_s: int | None = None) -> int:
    """Exponential backoff (60s · 2^attempts, capped 1h); 429 retry_after wins."""
    if retry_after_s is not None:
        return min(max(retry_after_s, 1), MAX_RETRY_AFTER_S)
    return min(BASE_BACKOFF_S * (2 ** max(attempts, 1)), MAX_BACKOFF_S)


def _send_telegram(
    http_client: httpx.Client,
    *,
    token: str,
    chat_id: str,
    text: str,
) -> tuple[bool, int | None, int | None, str]:
    """One sendMessage attempt.

    Returns (accepted, message_id, retry_after_s, error). accepted=True only
    on HTTP 200 with ok:true (provider-confirmed delivery). Definitive
    rejections (400 chat not found, 401 invalid token, 403 blocked bot)
    surface as accepted=False with no retry_after — the caller marks the row
    terminally FAILED.
    """
    response = http_client.post(
        f"{TELEGRAM_API}/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code == 200 and data.get("ok") is True:
        return True, data.get("result", {}).get("message_id"), None, ""
    if response.status_code == 429:
        retry_after = data.get("parameters", {}).get("retry_after")
        return False, None, int(retry_after) if retry_after else None, "rate limited (429)"
    if response.status_code in (400, 401, 403):
        # Definitive rejections: chat not found, invalid token, bot blocked.
        return False, None, None, f"rejected ({response.status_code}): {data.get('description', '')}"
    return False, None, None, f"http {response.status_code}: {data.get('description', '')}"


def process_outbox(
    db: Session,
    *,
    http_client: httpx.Client | None = None,
    settings=None,
    limit: int = 50,
    now=None,
) -> dict:
    """Drain due PENDING notifications. Returns a summary dict.

    Unconfigured channel (token or chat unset) is not an error: rows stay
    PENDING with attempts 0 and are counted as `unconfigured`.
    """
    cfg = settings or get_settings()
    token = cfg.telegram_bot_token.get_secret_value()
    chat_id = cfg.telegram_admin_chat_id
    moment = now or utcnow()
    due = list(
        db.scalars(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == "PENDING",
                NotificationOutbox.channel == "telegram",
            )
            .order_by(NotificationOutbox.created_at)
            .limit(limit)
        )
    )
    summary = {"due": len(due), "sent": 0, "failed": 0, "retried": 0, "unconfigured": 0}
    client = http_client or httpx.Client(timeout=cfg.llm_default_timeout_s)
    try:
        for row in due:
            if row.next_attempt_at is not None and row.next_attempt_at > moment:
                continue  # not due yet (backoff window)
            if not token or not (row.recipient or chat_id):
                summary["unconfigured"] += 1
                continue
            accepted, message_id, retry_after, error = _send_telegram(
                client,
                token=token,
                chat_id=row.recipient or chat_id,
                text=row.body,
            )
            row.attempts += 1
            if accepted:
                row.status = "SENT"
                row.provider_message_id = str(message_id or "")
                row.sent_at = utcnow()
                row.last_error = ""
                summary["sent"] += 1
            elif retry_after is None and error.startswith("rejected ("):
                # Definitive negative acceptance (docs/39): no retry.
                row.status = "FAILED"
                row.last_error = error
                summary["failed"] += 1
            elif row.attempts >= MAX_ATTEMPTS:
                row.status = "FAILED"
                row.last_error = f"{error} (after {row.attempts} attempts)"
                summary["failed"] += 1
            else:
                # Uncertain acceptance: retry later with backoff.
                row.last_error = error
                row.next_attempt_at = utcnow() + timedelta(
                    seconds=_next_delay_s(row.attempts, retry_after)
                )
                summary["retried"] += 1
        db.flush()
    finally:
        if http_client is None:
            client.close()
    return summary


def pending_count(db: Session) -> int:
    return len(
        list(
            db.scalars(
                select(NotificationOutbox).where(NotificationOutbox.status == "PENDING")
            )
        )
    )
