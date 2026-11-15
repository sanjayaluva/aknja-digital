"""Task-scoped routing + self-hosted IndicTrans2 adapter (T-023, docs/34 §3).

Rules under test:
- a product declaring `capability_contract["tasks"]` is admitted ONLY for its
  declared task profiles — including targeted (llm-ping style) calls;
- task-scoped products never serve generic (task=None) traffic;
- the indictrans2 adapter speaks OpenAI-compatible JSON to the worker base
  URL with the shared bearer token and the dist-200M default model;
- candidate registration seeds the indictrans2 entry with the tasks contract.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.modules.ai.inference import llm_complete
from app.modules.resources import service as quota
from app.modules.resources.candidates import register_candidate_providers
from app.modules.resources.models import ProviderAccount, ProviderProduct
from app.modules.resources.service import record_snapshot
from tests.test_ai_inference import _mock_client, _verify_provider


def _settings(**overrides) -> Settings:
    base = {
        "ai_provider_enabled": True,
        "groq_api_keys": "groq-key-1",
        "openrouter_api_key": "or-key-1",
        "indictrans2_base_url": "http://127.0.0.1:8001",
        "indictrans2_api_key": "worker-key-1",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _verify(db, seed, provider: str, *, verified_at, allowance: int = 1000) -> ProviderProduct:
    product = _verify_provider(db, seed, provider, allowance=allowance)
    account = db.query(ProviderAccount).filter(
        ProviderAccount.tenant_id == seed.tenant.id,
        ProviderAccount.provider == provider,
    ).one()
    account.last_verified_at = verified_at
    db.commit()
    return product


@pytest.fixture
def worker_capture():
    """Mock transport capturing the worker request; returns the translation."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        import json as _json
        seen["body"] = _json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "വിവർത്തനം ഫലം"}}]}
        )

    return seen, _mock_client(handler)


def test_candidate_registration_carries_tasks_contract(db, seed) -> None:
    stats = register_candidate_providers(db, seed.tenant.id)
    db.commit()
    assert stats["products"] > 0
    account = db.query(ProviderAccount).filter(
        ProviderAccount.tenant_id == seed.tenant.id,
        ProviderAccount.provider == "indictrans2",
    ).one()
    product = db.query(ProviderProduct).filter(
        ProviderProduct.account_id == account.id
    ).one()
    assert product.capability_contract["tasks"] == ["translation"]
    assert product.category == "AI_LLM"


def test_indictrans2_adapter_shape(db, seed, worker_capture) -> None:
    seen, client = worker_capture
    from app.core.security import utcnow
    from datetime import timedelta

    register_candidate_providers(db, seed.tenant.id)
    _verify(db, seed, "indictrans2", verified_at=utcnow())
    result = llm_complete(
        db, tenant_id=seed.tenant.id, task="translation",
        prompt="Translate to Malayalam:\nവാക്യം: hello world",
        target_provider="indictrans2",
        settings=_settings(), http_client=client,
    )
    assert result.status == "SUCCEEDED"
    assert result.provider == "indictrans2"
    assert result.model == "indictrans2-dist-200M"
    assert result.text == "വിവർത്തനം ഫലം"
    assert seen["url"] == "http://127.0.0.1:8001/v1/chat/completions"
    assert seen["auth"] == "Bearer worker-key-1"
    assert seen["body"]["model"] == "indictrans2-dist-200M"
    assert seen["body"]["messages"][0]["role"] == "user"


def test_task_scoped_product_rejected_for_other_tasks(db, seed, worker_capture) -> None:
    _, client = worker_capture
    from app.core.security import utcnow

    register_candidate_providers(db, seed.tenant.id)
    _verify(db, seed, "indictrans2", verified_at=utcnow())
    result = llm_complete(
        db, tenant_id=seed.tenant.id, task="summarization",  # not declared
        prompt="summarize this", target_provider="indictrans2",
        settings=_settings(), http_client=client,
    )
    assert result.status == "PENDING_MANUAL"
    assert "task contract" in result.reason and "summarization" in result.reason


def test_task_scoped_product_never_serves_generic_traffic(db, seed) -> None:
    from app.core.security import utcnow

    register_candidate_providers(db, seed.tenant.id)
    _verify(db, seed, "indictrans2", verified_at=utcnow())
    decision = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=quota.ProviderCategory.AI_LLM,
        quantity=1, idempotency_key="generic-tool-call",
    )
    assert not decision.admitted
    assert "generic" in decision.reason


def test_translation_routes_to_task_scoped_worker_over_universal(
    db, seed, worker_capture
) -> None:
    """With both a universal (groq) and the task-scoped worker verified, a
    translation call must land on the worker even though groq is also
    eligible — the task contract is a routing signal, not just a guard."""
    seen, client = worker_capture
    from app.core.security import utcnow
    from datetime import timedelta

    register_candidate_providers(db, seed.tenant.id)
    _verify(db, seed, "groq", verified_at=utcnow() - timedelta(minutes=5))
    _verify(db, seed, "indictrans2", verified_at=utcnow())
    result = llm_complete(
        db, tenant_id=seed.tenant.id, task="translation", prompt="translate this",
        settings=_settings(), http_client=client,
    )
    assert result.status == "SUCCEEDED"
    assert result.provider == "indictrans2"
    assert seen["url"].startswith("http://127.0.0.1:8001")


def test_generic_task_still_reaches_universal_product(db, seed) -> None:
    """Classification keeps flowing to the universal pool when only the
    worker is task-scoped (worker must not intercept generic tasks)."""
    from app.core.security import utcnow

    register_candidate_providers(db, seed.tenant.id)
    _verify(db, seed, "groq", verified_at=utcnow())
    _verify(db, seed, "indictrans2", verified_at=utcnow())
    decision = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=quota.ProviderCategory.AI_LLM,
        quantity=1, idempotency_key="classify-call", task="classification",
    )
    assert decision.admitted
    product = db.get(ProviderProduct, decision.provider_product_id)
    account = db.get(ProviderAccount, product.account_id)
    assert account.provider == "groq"
