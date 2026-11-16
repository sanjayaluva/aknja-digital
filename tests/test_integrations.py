"""Credential hub tests (docs/34, T-027)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
from sqlalchemy import select

from app.core.config import Settings
from app.modules.identity.service import Principal
from app.modules.integrations import service as integrations
from app.modules.integrations.models import IntegrationCredential


def _principal(seed) -> Principal:
    from app.core.enums import UserRole

    return Principal(user_id=seed.admin.id, email=seed.admin.email,
                     tenant_id=seed.tenant.id, role=UserRole.SUPER_ADMIN,
                     client_id=None, session_id=seed.admin.id, csrf_token="t")


def test_save_and_resolve_roundtrip(db, seed):
    p = _principal(seed)
    row = integrations.save_credential(
        db, principal=p, provider_key="gemini", provider_type="LLM",
        secrets={"api_key": "DB-KEY-1"}, config={"model": "gemini-2.5-flash"})
    db.commit()
    assert row.status == "DRAFT"

    # DRAFT does not resolve — only ACTIVE rows feed the gateway
    assert integrations.resolve_secrets(db, seed.tenant.id, "gemini") is None
    row = integrations.set_status(db, principal=p, credential_id=row.id,
                                  status="ACTIVE")
    db.commit()
    assert integrations.resolve_secrets(db, seed.tenant.id, "gemini") == {
        "api_key": "DB-KEY-1"}

    # the stored blob is really encrypted (no plaintext in the column)
    fresh = db.scalar(select(IntegrationCredential).where(
        IntegrationCredential.provider_key == "gemini"))
    assert "DB-KEY-1" not in fresh.payload_encrypted


def test_resolve_llm_key_db_first_env_fallback(db, seed, monkeypatch):
    import app.modules.integrations.service as svc
    p = _principal(seed)

    # no DB row -> env fallback path (settings carry a fake gemini key)
    settings = Settings(gemini_api_keys="ENV-KEY-A,ENV-KEY-B")
    assert svc.resolve_llm_key(db, seed.tenant.id, "gemini", settings) == "ENV-KEY-A"

    # ACTIVE DB row with a pool wins over env
    integrations.save_credential(
        db, principal=p, provider_key="groq", provider_type="LLM",
        secrets={"api_keys": "DB-G1,DB-G2"})
    row = db.scalar(select(IntegrationCredential).where(
        IntegrationCredential.provider_key == "groq"))
    integrations.set_status(db, principal=p, credential_id=row.id, status="ACTIVE")
    db.commit()
    settings = Settings(groq_api_keys="ENV-GROQ")
    assert svc.resolve_llm_key(db, seed.tenant.id, "groq", settings) == "DB-G1"

    # deactivation must actually switch resolution back (fail-closed intent)
    integrations.set_status(db, principal=p, credential_id=row.id, status="INACTIVE")
    db.commit()
    assert svc.resolve_llm_key(db, seed.tenant.id, "groq", settings) == "ENV-GROQ"


def test_update_keeps_secret_when_omitted(db, seed):
    p = _principal(seed)
    row = integrations.save_credential(
        db, principal=p, provider_key="telegram_bot", provider_type="MESSAGING",
        secrets={"bot_token": "123:SECRET"})
    db.commit()
    blob = row.payload_encrypted
    integrations.save_credential(
        db, principal=p, provider_key="telegram_bot", provider_type="MESSAGING",
        name="Founder bot", secrets=None, config={"chat_id": "42"})
    db.commit()
    assert row.payload_encrypted == blob  # secret untouched
    assert row.name == "Founder bot" and row.config == {"chat_id": "42"}


def test_masked_hint_never_leaks(db, seed):
    p = _principal(seed)
    row = integrations.save_credential(
        db, principal=p, provider_key="openrouter", provider_type="LLM",
        secrets={"api_key": "sk-or-v1-abcdef123456"})
    db.commit()
    hint = integrations.masked_hint(row)
    assert "abcdef123456" not in hint and "sk-or" not in hint
    assert "…" in hint


def test_credential_test_pass_activates_and_fail_breaks(db, seed, monkeypatch):
    p = _principal(seed)
    row = integrations.save_credential(
        db, principal=p, provider_key="gemini", provider_type="LLM",
        secrets={"api_key": "K"})
    integrations.set_status(db, principal=p, credential_id=row.id, status="ACTIVE")
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("x-goog-api-key") == "K":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(401, json={"error": "bad key"})

    transport = httpx.MockTransport(handler)
    fake_httpx = SimpleNamespace(
        Client=lambda *a, **k: httpx.Client(transport=transport))
    monkeypatch.setattr(integrations, "httpx", fake_httpx)
    try:
        out = integrations.test_credential(db, principal=p, credential_id=row.id)
        assert out.last_test_result["ok"] is True
        assert out.status == "ACTIVE"

        # a failing key flips an ACTIVE row to FAILED (stops resolution)
        integrations.save_credential(
            db, principal=p, provider_key="gemini", provider_type="LLM",
            secrets={"api_key": "WRONG"})
        out = integrations.test_credential(db, principal=p, credential_id=row.id)
        assert out.last_test_result["ok"] is False
        assert out.status == "FAILED"
    finally:
        pass  # monkeypatch undoes the swap
