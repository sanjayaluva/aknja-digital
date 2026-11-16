"""Telegram inbound webhook tests (docs/34, T-029)."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import UserRole
from app.modules.identity.service import Principal
from app.modules.integrations import service as integrations
from app.modules.integrations.models import IntegrationCredential
from app.modules.intake.models import IntakeMessage


def _principal(seed) -> Principal:
    return Principal(user_id=seed.admin.id, email=seed.admin.email,
                     tenant_id=seed.tenant.id, role=UserRole.SUPER_ADMIN,
                     client_id=None, session_id=seed.admin.id, csrf_token="t")


def _register_bot(db, seed, secret="sec123"):
    integrations.save_credential(
        db, principal=_principal(seed), provider_key="telegram_bot",
        provider_type="MESSAGING", name="Intake bot",
        secrets={"bot_token": "111:FAKE", "webhook_secret": secret},
        config={"public_base_url": "https://aknja.pp.ua"})
    row = db.scalar(select(IntegrationCredential).where(
        IntegrationCredential.provider_key == "telegram_bot"))
    integrations.set_status(db, principal=_principal(seed),
                            credential_id=row.id, status="ACTIVE")
    db.commit()
    return row


def _client():
    from app.main import app
    return TestClient(app)


_UPDATE = {
    "update_id": 1001,
    "message": {"message_id": 42, "text": "Enik oru website venam, budget 10000",
                "from": {"id": 7, "username": "cust_one"},
                "chat": {"id": 7, "type": "private"}},
}


def _mock_ai(monkeypatch):
    import app.modules.intake.service as intake_svc

    def fake_llm(db_, *, tenant_id, task, prompt, **kw):
        if task == "requirements":
            return SimpleNamespace(
                status="SUCCEEDED", provider="groq", reason="",
                text=('{"requirements": ["website"], "missing_info": ["type"], '
                      '"suggested_title": "Customer Website"}'))
        return SimpleNamespace(
            status="SUCCEEDED", provider="groq", reason="",
            text=('{"is_project_inquiry": true, "service_domain": "OTHER", '
                  '"language": "ml", "urgency": "normal", "summary": "wants a website"}'))
    monkeypatch.setattr(intake_svc, "llm_complete", fake_llm)


def test_webhook_rejects_unknown_bot_and_bad_secret(db, seed):
    c = _client()
    r = c.post("/hooks/telegram/telegram_bot", json=_UPDATE)
    assert r.status_code == 404  # no credential at all

    _register_bot(db, seed)
    r = c.post("/hooks/telegram/telegram_bot", json=_UPDATE,
               headers={"X-Telegram-Bot-Api-Secret-Token": "WRONG"})
    assert r.status_code == 403
    # missing header is also rejected
    r2 = c.post("/hooks/telegram/telegram_bot", json=_UPDATE)
    assert r2.status_code == 403


def test_webhook_ingests_and_deduplicates(db, seed, monkeypatch):
    _mock_ai(monkeypatch)
    _register_bot(db, seed)
    c = _client()
    headers = {"X-Telegram-Bot-Api-Secret-Token": "sec123"}

    r = c.post("/hooks/telegram/telegram_bot", json=_UPDATE, headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "CONVERTED"
    rows = db.scalars(select(IntakeMessage).where(
        IntakeMessage.channel == "TELEGRAM")).all()
    assert len(rows) == 1
    assert rows[0].sender == "@cust_one"
    assert rows[0].external_id == "telegram:1001"
    assert rows[0].lead_id is not None

    # Telegram retry of the same update_id: no double ingest
    r2 = c.post("/hooks/telegram/telegram_bot", json=_UPDATE, headers=headers)
    assert r2.status_code == 200 and r2.json().get("duplicate") is True
    rows = db.scalars(select(IntakeMessage).where(
        IntakeMessage.channel == "TELEGRAM")).all()
    assert len(rows) == 1


def test_webhook_defers_non_text_updates(db, seed):
    _register_bot(db, seed)
    c = _client()
    r = c.post("/hooks/telegram/telegram_bot",
               json={"update_id": 1002, "message": {"message_id": 43,
                     "voice": {"duration": 7}, "chat": {"id": 7}}},
               headers={"X-Telegram-Bot-Api-Secret-Token": "sec123"})
    assert r.status_code == 200 and r.json().get("deferred")
    # nothing ingested for a voice note (T-031 wires transcription)
    assert db.scalar(select(IntakeMessage).where(
        IntakeMessage.external_id == "telegram:1002")) is None
