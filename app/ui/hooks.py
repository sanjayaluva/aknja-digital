"""Public service webhooks (docs/34, T-029).

POST /hooks/telegram/{provider_key} — inbound Telegram updates for a bot
whose token + webhook secret live in the credential hub. Verified by the
X-Telegram-Bot-Api-Secret-Token header set at setWebhook time.

Ordering matters: the update is deduplicated and persisted BEFORE the
governed AI pipeline runs, so the endpoint answers Telegram in
milliseconds; a Telegram retry after a slow AI call cannot double-ingest
(external_id = "telegram:{update_id}" is unique).
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core.config import get_settings
from app.modules.governance.service import record_audit
from app.modules.integrations.models import IntegrationCredential
from app.modules.integrations.service import _decrypt
from app.ui.admin import db_session

router = APIRouter(include_in_schema=False)


@router.post("/hooks/telegram/{provider_key}")
async def telegram_webhook(
    request: Request,
    provider_key: str,
    x_telegram_bot_api_secret_token: str = Header(default=""),
) -> JSONResponse:
    db = db_session()
    try:
        row = db.scalar(
            select(IntegrationCredential).where(
                IntegrationCredential.provider_key == provider_key,
                IntegrationCredential.provider_type == "MESSAGING",
                IntegrationCredential.status == "ACTIVE",
            )
        )
        if row is None:
            return JSONResponse({"error": "unknown bot"}, status_code=404)
        secrets = _decrypt(get_settings(), row.payload_encrypted)
        expected = secrets.get("webhook_secret", "")
        if not expected or x_telegram_bot_api_secret_token != expected:
            record_audit(
                db, tenant_id=row.tenant_id, actor_type="SYSTEM",
                actor_id="telegram_webhook", action="telegram.webhook_rejected",
                resource_type="integration_credential", resource_id=str(row.id),
                payload={"reason": "bad or missing secret token"},
            )
            db.commit()
            return JSONResponse({"error": "forbidden"}, status_code=403)

        update = await request.json()
        message = (update or {}).get("message") or {}
        update_id = str((update or {}).get("update_id") or "")
        text = (message.get("text") or "").strip()
        from_user = message.get("from") or {}
        sender = ("@" + from_user["username"] if from_user.get("username")
                  else str((message.get("chat") or {}).get("id") or "unknown"))
        if not text:
            # voice/photo/etc. arrive with T-031; acknowledge so Telegram
            # does not retry an update we intentionally defer
            return JSONResponse({"ok": True, "deferred": "non-text update"})

        from app.modules.integrations.email_poll import system_principal
        from app.modules.intake import service as intake
        from app.modules.intake.models import IntakeMessage

        # 1) idempotency: a retry of the same update_id is a no-op
        external_id = f"telegram:{update_id}" if update_id else None
        if external_id and db.scalar(select(IntakeMessage).where(
                IntakeMessage.external_id == external_id)):
            return JSONResponse({"ok": True, "duplicate": True})

        # 2) persist first, ACK fast — the AI pipeline runs on the same
        #    record through the shared intake code path
        record = intake.submit_intake_message(
            db, principal=system_principal(db), channel="TELEGRAM",
            sender=sender, content=text, external_id=external_id,
        )
        db.commit()
        return JSONResponse({"ok": True, "status": record.status})
    except Exception as exc:  # noqa: BLE001 — webhook must never 500-loop
        db.rollback()
        record_audit(
            db, tenant_id=None, actor_type="SYSTEM", actor_id="telegram_webhook",
            action="telegram.webhook_error",
            resource_type="integration_credential", resource_id=provider_key,
            payload={"error": str(exc)[:200]},
        )
        db.commit()
        return JSONResponse({"ok": False}, status_code=200)  # no retry storm
    finally:
        db.close()
