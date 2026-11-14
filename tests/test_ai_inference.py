"""LLM inference layer tests (v5.3.2 §5C, SRS §8.4 Layer 1).

Rules under test:
- fail closed: no verified provider / master switch off -> PENDING_MANUAL
  with a reason (never a silent degrade, never a paid fallback);
- a verified + enabled provider with a settings key succeeds through its
  HTTP adapter and the quota engine records the reservation;
- retryable failures (429) fail over to the next eligible provider and the
  switch is audited;
- the governed `llm.generate` tool runs through the same layer and blocks
  CONFIDENTIAL data from egressing to third-party models.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.enums import BillingState, DataClassification
from app.modules.ai.gateway import ToolGateway, seed_builtin_tools
from app.modules.ai.inference import llm_complete
from app.modules.ai.models import LLMCallLog
from app.modules.governance.models import AuditEvent
from app.modules.identity.service import Principal
from app.modules.resources import service as quota
from app.modules.resources.candidates import register_candidate_providers
from app.modules.resources.models import ProviderAccount, ProviderProduct
from app.modules.resources.service import record_snapshot


def _settings(**overrides) -> Settings:
    base = {
        "ai_provider_enabled": True,
        "groq_api_keys": "groq-key-1",
        "github_models_token": "github-key-1",
        "gemini_api_keys": "gemini-key-1",
        "cloudflare_api_token": "cf-key-1",
        "cloudflare_account_id": "cf-account",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _verify_provider(db, seed, provider: str, allowance: int = 1000) -> ProviderProduct:
    account = (
        db.query(ProviderAccount)
        .filter(
            ProviderAccount.tenant_id == seed.tenant.id,
            ProviderAccount.provider == provider,
        )
        .one()
    )
    product = (
        db.query(ProviderProduct)
        .filter(ProviderProduct.account_id == account.id)
        .one()
    )
    account.billing_state = BillingState.FREE_VERIFIED.value
    account.enabled = True
    product.allowance = allowance
    product.enabled = True
    record_snapshot(db, product, locally_metered=0)
    db.commit()
    return product


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5)


def _groq_ok(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "api.groq.com"
    assert request.headers["Authorization"] == "Bearer groq-key-1"
    return httpx.Response(
        200, json={"choices": [{"message": {"content": "PONG from groq"}}]}
    )


def test_llm_fails_closed_without_verified_provider(db, seed) -> None:
    register_candidate_providers(db, seed.tenant.id)
    db.commit()
    result = llm_complete(
        db, tenant_id=seed.tenant.id, task="classification", prompt="ping",
        settings=_settings(), http_client=_mock_client(lambda r: httpx.Response(200, json={})),
    )
    assert result.status == "PENDING_MANUAL"
    assert "no eligible FREE_VERIFIED" in result.reason
    log = db.scalar(select(LLMCallLog).order_by(LLMCallLog.created_at.desc()))
    assert log is not None and log.status == "PENDING_MANUAL"


def test_llm_fails_closed_when_master_switch_off(db, seed) -> None:
    result = llm_complete(
        db, tenant_id=seed.tenant.id, task="classification", prompt="ping",
        settings=_settings(ai_provider_enabled=False),
        http_client=_mock_client(lambda r: httpx.Response(200, json={})),
    )
    assert result.status == "PENDING_MANUAL"
    assert "AI_PROVIDER_ENABLED=false" in result.reason


def test_llm_success_via_verified_groq(db, seed) -> None:
    register_candidate_providers(db, seed.tenant.id)
    product = _verify_provider(db, seed, "groq")
    result = llm_complete(
        db, tenant_id=seed.tenant.id, task="classification", prompt="ping",
        settings=_settings(), http_client=_mock_client(_groq_ok),
    )
    assert result.status == "SUCCEEDED"
    assert result.text == "PONG from groq"
    assert result.provider == "groq"
    assert result.model == "llama-3.3-70b-versatile"
    reservation = db.query(quota.QuotaReservation).filter_by(
        provider_product_id=product.id
    ).first()
    assert reservation is not None and reservation.quantity == 1
    # The audit ledger is hash-chained: raw payloads are not persisted, so
    # assert on the action + resource binding instead.
    audit = db.query(AuditEvent).filter(AuditEvent.action == "llm.succeeded").one()
    assert audit.resource_type == "provider_product"
    assert audit.resource_id == str(product.id)
    log = db.scalar(select(LLMCallLog).order_by(LLMCallLog.created_at.desc()))
    assert log.status == "SUCCEEDED"
    assert log.prompt_hash  # hash stored, never the raw prompt
    assert "ping" not in (log.error or "")


def test_llm_failover_on_429_to_next_provider(db, seed) -> None:
    register_candidate_providers(db, seed.tenant.id)
    groq = _verify_provider(db, seed, "groq")
    _verify_provider(db, seed, "github_models")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.groq.com":
            return httpx.Response(429, json={"error": "rate limited"})
        assert request.url.host == "models.github.ai"
        assert request.headers["Authorization"] == "Bearer github-key-1"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "PONG from github"}}]}
        )

    result = llm_complete(
        db, tenant_id=seed.tenant.id, task="summarization", prompt="ping",
        settings=_settings(), http_client=_mock_client(handler),
    )
    assert result.status == "SUCCEEDED"
    assert result.provider == "github_models"
    assert result.text == "PONG from github"
    assert result.attempts[0]["provider"] == "groq"
    assert result.attempts[0]["status"] == "FAILED"
    switch = db.query(AuditEvent).filter(AuditEvent.action == "llm.failover").one()
    assert switch.resource_type == "provider_product"
    assert switch.resource_id == str(groq.id)
    _ = switch  # the switch event binds to the provider we failed away from


def test_llm_ping_denies_unverified_target(db, seed) -> None:
    register_candidate_providers(db, seed.tenant.id)
    db.commit()
    result = llm_complete(
        db, tenant_id=seed.tenant.id, task="classification", prompt="ping",
        target_provider="groq", settings=_settings(),
        http_client=_mock_client(lambda r: httpx.Response(200, json={})),
    )
    assert result.status == "PENDING_MANUAL"
    assert "not eligible" in result.reason


def test_gateway_llm_generate_tool_success(db, seed, monkeypatch) -> None:
    register_candidate_providers(db, seed.tenant.id)
    _verify_provider(db, seed, "groq")
    seed_builtin_tools(db)
    db.commit()

    import app.modules.ai.inference as inference_module

    test_settings = _settings()
    monkeypatch.setattr(inference_module, "get_settings", lambda: test_settings)

    gateway = ToolGateway(db)
    principal = Principal(
        user_id=seed.admin.id, email=seed.admin.email, tenant_id=seed.tenant.id,
        role="SUPER_ADMIN", client_id=None, session_id=seed.admin.id, csrf_token="",
    )
    client = _mock_client(_groq_ok)
    original_client = httpx.Client

    def _patched_client_factory(*args, **kwargs):
        return client

    monkeypatch.setattr(inference_module.httpx, "Client", _patched_client_factory)
    execution = gateway.execute_tool(
        principal=principal,
        tool_name="llm.generate",
        arguments={
            "task": "classification",
            "prompt": "ping",
            "data_classification": DataClassification.INTERNAL.value,
        },
        idempotency_key="llm-tool-1",
    )
    db.commit()
    assert execution.status == "SUCCEEDED"
    assert execution.result["status"] == "SUCCEEDED"
    assert execution.result["provider"] == "groq"
    assert execution.result["text"] == "PONG from groq"
    _ = original_client


def test_gateway_llm_generate_blocks_confidential_data(db, seed, monkeypatch) -> None:
    """CONFIDENTIAL client data must never egress to a third-party model."""
    register_candidate_providers(db, seed.tenant.id)
    _verify_provider(db, seed, "groq")
    seed_builtin_tools(db)
    db.commit()

    import app.modules.ai.inference as inference_module

    monkeypatch.setattr(
        inference_module, "get_settings", lambda: _settings()
    )
    gateway = ToolGateway(db)
    principal = Principal(
        user_id=seed.admin.id, email=seed.admin.email, tenant_id=seed.tenant.id,
        role="SUPER_ADMIN", client_id=None, session_id=seed.admin.id, csrf_token="",
    )
    from app.core.errors import PolicyBlockedError

    with pytest.raises(PolicyBlockedError):
        gateway.execute_tool(
            principal=principal,
            tool_name="llm.generate",
            arguments={
                "task": "classification",
                "prompt": "confidential client brief",
                "data_classification": DataClassification.CONFIDENTIAL.value,
            },
            idempotency_key="llm-tool-2",
        )


def test_unknown_task_is_rejected(db, seed) -> None:
    with pytest.raises(ValueError, match="unknown task"):
        llm_complete(
            db, tenant_id=seed.tenant.id, task="nonexistent", prompt="x",
            settings=_settings(),
        )
