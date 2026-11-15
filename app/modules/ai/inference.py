"""Provider-neutral LLM inference layer (v5.3.2 §5C, SRS §8.4 Layer 1).

Selection flow for every call:
  1. admit quota from the best eligible FREE_VERIFIED AI_LLM product
     (fail closed: no verified provider -> PENDING_MANUAL, never a silent
     degrade and never a paid fallback);
  2. dispatch through the provider's HTTP adapter with a normalized
     request/response shape;
  3. on a retryable failure (HTTP 429/5xx, timeout) audit the failover
     event and try the next eligible provider, excluding the failed one
     (v5.3.2 §3 step 14);
  4. log every attempt in llm_call_logs with a prompt HASH only — raw
     prompts may contain client content and are never persisted.

API keys come from settings (never the database, docs/23) and are only the
first gate: the provider registry must also hold the account as
FREE_VERIFIED + enabled before anything is admitted.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.enums import ProviderCategory
from app.core.security import canonical_payload_hash
from app.modules.ai.benchmark import benchmark_gate
from app.modules.ai.models import LLMCallLog
from app.modules.governance.service import record_audit
from app.modules.resources.models import ProviderAccount, ProviderProduct
from app.modules.resources.service import admit_usage

TEMPLATE_VERSION = "v1"

# Task profiles (v5.3.2 §5C). Each task declares the quality contract the
# model must satisfy; structured_output tasks additionally require the
# caller to validate the returned text against its schema (never trust
# model output).
TASK_PROFILES: dict[str, dict[str, Any]] = {
    "classification": {"min_context_tokens": 4096, "structured_output": False, "temperature": 0.0},
    "translation": {"min_context_tokens": 8192, "structured_output": False, "temperature": 0.2},
    "summarization": {"min_context_tokens": 8192, "structured_output": False, "temperature": 0.2},
    "requirements": {"min_context_tokens": 16384, "structured_output": True, "temperature": 0.2},
    "code_review": {"min_context_tokens": 32768, "structured_output": True, "temperature": 0.0},
    "proposal_draft": {"min_context_tokens": 16384, "structured_output": False, "temperature": 0.4},
    "qa_review": {"min_context_tokens": 16384, "structured_output": True, "temperature": 0.0},
}


class LLMProviderError(Exception):
    """Adapter failure; `retryable` mirrors HTTP 429/5xx/timeout semantics."""

    def __init__(self, provider: str, message: str, *, retryable: bool) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.retryable = retryable


@dataclass
class LLMResult:
    status: str  # SUCCEEDED | PENDING_MANUAL | FAILED
    text: str = ""
    provider: str = ""
    model: str = ""
    latency_ms: int = 0
    reason: str = ""
    attempts: list[dict[str, Any]] = field(default_factory=list)


# --- provider adapters ---------------------------------------------------------
# Each adapter normalizes one provider API to (prompt, model) -> text.
# Default models are the free-tier defaults named by the SRS / provider
# docs at research time; callers may always override via `model=`.


def _total_budget_s(settings: Settings) -> float:
    """TOTAL wall-clock budget per LLM HTTP request.

    httpx per-read timeouts cannot bound a trickling free-tier response
    (observed live 2026-11-15: an oversubscribed :free model streamed a
    single completion for 7+ minutes, one chunk at a time). Requests are
    therefore streamed under one explicit budget; over budget means the
    provider is too slow and the error is retryable so failover moves on.
    """
    return max(60.0, settings.llm_default_timeout_s * 3.0)


def _request_json(
    client: httpx.Client,
    method: str,
    provider: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict,
    budget_s: float,
) -> dict:
    """One provider HTTP call; returns the parsed JSON body under a total budget."""
    started = time.monotonic()
    try:
        with client.stream(method, url, headers=headers, json=json_body) as response:
            if response.status_code == 429 or response.status_code >= 500:
                raise LLMProviderError(
                    provider, f"HTTP {response.status_code} (retryable)", retryable=True
                )
            if response.status_code >= 400:
                body = response.read().decode(errors="replace")
                raise LLMProviderError(
                    provider, f"HTTP {response.status_code}: {body[:200]}", retryable=False
                )
            chunks: list[bytes] = []
            for chunk in response.iter_bytes():
                chunks.append(chunk)
                if time.monotonic() - started > budget_s:
                    raise LLMProviderError(
                        provider,
                        f"total request budget {budget_s:.1f}s exceeded "
                        "(provider stream too slow)",
                        retryable=True,
                    )
            return json.loads(b"".join(chunks))
    except httpx.TimeoutException as exc:
        raise LLMProviderError(provider, f"timeout: {exc}", retryable=True) from exc


def _openai_compatible(
    *,
    provider: str,
    url: str,
    api_key: str,
    model: str,
    prompt: str,
    temperature: float,
    client: httpx.Client,
    total_budget_s: float = 60.0,
) -> str:
    payload = _request_json(
        client, "POST", provider, url,
        headers={"Authorization": f"Bearer {api_key}"},
        json_body={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        },
        budget_s=total_budget_s,
    )
    try:
        return str(payload["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMProviderError(provider, f"unexpected response shape: {exc}") from exc


def _adapter_groq(prompt: str, model: str, key: str, settings: Settings, client: httpx.Client) -> str:
    # Groq retired the un-namespaced llama defaults (404 model_not_found,
    # 2026-11 live run); the namespaced gpt-oss line is the current free pool.
    return _openai_compatible(
        provider="groq",
        url="https://api.groq.com/openai/v1/chat/completions",
        api_key=key,
        model=model or "openai/gpt-oss-20b",
        prompt=prompt,
        temperature=0.2,
        client=client,
        total_budget_s=_total_budget_s(settings),
    )


def _adapter_github_models(
    prompt: str, model: str, key: str, settings: Settings, client: httpx.Client
) -> str:
    return _openai_compatible(
        provider="github_models",
        url="https://models.github.ai/inference/chat/completions",
        api_key=key,
        model=model or "openai/gpt-4o-mini",
        prompt=prompt,
        temperature=0.2,
        client=client,
        total_budget_s=_total_budget_s(settings),
    )


def _adapter_gemini(prompt: str, model: str, key: str, settings: Settings, client: httpx.Client) -> str:
    # 2.5-flash is retired for new users (404 guidance names gemini-3.8-flash,
    # 2026-11 live run). NOTE (T-023g): generateContent is region-blocked for
    # this account from the sandbox AND the OCI egress ("User location is not
    # supported" / silent drop) — keep the product disabled until the founder
    # verifies from an allowed region (docs/33).
    resolved = model or "gemini-3.8-flash"
    payload = _request_json(
        client, "POST", "gemini",
        f"https://generativelanguage.googleapis.com/v1beta/models/{resolved}:generateContent",
        headers={"x-goog-api-key": key},
        json_body={"contents": [{"parts": [{"text": prompt}]}]},
        budget_s=_total_budget_s(settings),
    )
    try:
        return str(payload["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMProviderError("gemini", f"unexpected response shape: {exc}") from exc


def _adapter_workers_ai(
    prompt: str, model: str, key: str, settings: Settings, client: httpx.Client
) -> str:
    account = settings.cloudflare_account_id
    if not account:
        raise LLMProviderError("cloudflare_workers_ai", "CLOUDFLARE_ACCOUNT_ID is not set", retryable=False)
    resolved = model or "@cf/meta/llama-3.1-8b-instruct"
    payload = _request_json(
        client, "POST", "cloudflare_workers_ai",
        f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{resolved}",
        headers={"Authorization": f"Bearer {key}"},
        json_body={"messages": [{"role": "user", "content": prompt}]},
        budget_s=_total_budget_s(settings),
    )
    try:
        return str(payload["result"]["response"])
    except (KeyError, TypeError) as exc:
        raise LLMProviderError("cloudflare_workers_ai", f"unexpected response shape: {exc}") from exc


def _adapter_openrouter(
    prompt: str, model: str, key: str, settings: Settings, client: httpx.Client
) -> str:
    # Only `:free` slugs are admissible (SRS §8.4 Layer 1; registry note).
    resolved = model or "inclusionai/ling-3.2-flash:free"  # live-proven 2026-11-15; gemma-4 :free 400s in restricted regions
    return _openai_compatible(
        provider="openrouter",
        url="https://openrouter.ai/api/v1/chat/completions",
        api_key=key,
        model=resolved,
        prompt=prompt,
        temperature=0.2,
        client=client,
        total_budget_s=_total_budget_s(settings),
    )


def _adapter_mistral(
    prompt: str, model: str, key: str, settings: Settings, client: httpx.Client
) -> str:
    resolved = model or "mistral-small-latest"
    return _openai_compatible(
        provider="mistral",
        url="https://api.mistral.ai/v1/chat/completions",
        api_key=key,
        model=resolved,
        prompt=prompt,
        temperature=0.2,
        client=client,
        total_budget_s=_total_budget_s(settings),
    )


def _adapter_indictrans2(
    prompt: str, model: str, key: str, settings: Settings, client: httpx.Client
) -> str:
    """Self-hosted IndicTrans2-dist-200M worker (docs/34 §3 decision).

    The worker is an OpenAI-compatible shim (en<->{ml,hi,ta}) running on OCI
    instance-2; reached over the reverse SSH tunnel, hence the localhost
    default. Translation-only: its registry product carries
    `capability_contract["tasks"] = ["translation"]` so the quota engine
    never routes generic traffic to it.
    """
    return _openai_compatible(
        provider="indictrans2",
        url=f"{settings.indictrans2_base_url.rstrip('/')}/v1/chat/completions",
        api_key=key,
        model=model or "indictrans2-dist-200M",
        prompt=prompt,
        temperature=0.2,
        client=client,
        total_budget_s=_total_budget_s(settings),
    )


ADAPTERS = {
    "groq": _adapter_groq,
    "github_models": _adapter_github_models,
    "gemini": _adapter_gemini,
    "cloudflare_workers_ai": _adapter_workers_ai,
    "openrouter": _adapter_openrouter,
    "mistral": _adapter_mistral,
    "indictrans2": _adapter_indictrans2,
}


def _provider_key(provider: str, settings: Settings) -> str:
    """First key of a comma-separated key pool (SRS GEMINI_API_KEYS=key1,key2)."""
    raw = {
        "groq": settings.groq_api_keys,
        "gemini": settings.gemini_api_keys,
        "github_models": settings.github_models_token,
        "cloudflare_workers_ai": settings.cloudflare_api_token,
        "openrouter": settings.openrouter_api_key,
        "mistral": settings.mistral_api_key,
        "indictrans2": settings.indictrans2_api_key,
    }.get(provider)
    secret = raw.get_secret_value() if raw is not None else ""
    return secret.split(",")[0].strip() if secret else ""


def _log_call(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    task: str,
    provider: str,
    model: str,
    status: str,
    latency_ms: int,
    prompt_hash: str,
    error: str | None = None,
) -> None:
    db.add(
        LLMCallLog(
            tenant_id=tenant_id,
            task=task,
            provider=provider,
            model=model,
            status=status,
            latency_ms=latency_ms,
            prompt_hash=prompt_hash,
            template_version=TEMPLATE_VERSION,
            error=error,
        )
    )
    db.flush()


def _target_product(
    db: Session, tenant_id: uuid.UUID, provider: str
) -> tuple[ProviderProduct, ProviderAccount] | None:
    row = db.execute(
        select(ProviderProduct, ProviderAccount)
        .join(ProviderAccount, ProviderProduct.account_id == ProviderAccount.id)
        .where(
            ProviderAccount.tenant_id == tenant_id,
            ProviderAccount.provider == provider,
            ProviderProduct.category == ProviderCategory.AI_LLM.value,
        )
    ).first()
    return (row[0], row[1]) if row else None


def llm_complete(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    task: str,
    prompt: str,
    model: str | None = None,
    target_provider: str | None = None,
    max_attempts: int = 3,
    http_client: httpx.Client | None = None,
    settings: Settings | None = None,
) -> LLMResult:
    """Run one LLM task through the free-provider pool with failover.

    Fail-closed guarantees (v5.3.2 §5C): if no eligible free provider
    exists the result is PENDING_MANUAL with a reason — the caller queues
    or escalates; client deliverables are never silently degraded.
    """
    if task not in TASK_PROFILES:
        raise ValueError(f"unknown task '{task}' (expected one of {sorted(TASK_PROFILES)})")
    settings = settings or get_settings()
    prompt_hash = canonical_payload_hash({"task": task, "prompt": prompt})
    result = LLMResult(status="PENDING_MANUAL", reason="")
    own_client = http_client is None
    client = http_client or httpx.Client(timeout=settings.llm_default_timeout_s)

    # Master switch (SRS §14): adapters stay off until explicitly enabled.
    if not settings.ai_provider_enabled:
        result.reason = "AI_PROVIDER_ENABLED=false — enable the master switch after provider verification"
        _log_call(db, tenant_id=tenant_id, task=task, provider="-", model="-",
                  status="PENDING_MANUAL", latency_ms=0, prompt_hash=prompt_hash,
                  error=result.reason)
        return result

    try:
        exclude: list[uuid.UUID] = []
        attempts_left = 1 if target_provider else max_attempts

        # Resolve a targeted product once (llm-ping "Test provider" action).
        target_product_id: uuid.UUID | None = None
        if target_provider is not None:
            pair = _target_product(db, tenant_id, target_provider)
            if pair is None:
                result.reason = (
                    f"provider '{target_provider}' has no AI_LLM product registered — "
                    "run register-provider-candidates"
                )
                _log_call(db, tenant_id=tenant_id, task=task, provider=target_provider, model="-",
                          status="PENDING_MANUAL", latency_ms=0, prompt_hash=prompt_hash,
                          error=result.reason)
                return result
            target_product_id = pair[0].id

        while attempts_left > 0:
            attempts_left -= 1
            decision = admit_usage(
                db,
                tenant_id=tenant_id,
                category=ProviderCategory.AI_LLM,
                quantity=1,
                idempotency_key=f"llm:{uuid.uuid4()}",
                product_id=target_product_id,
                exclude_product_ids=exclude or None,
                task=task,
            )
            if not decision.admitted:
                if not result.attempts and target_provider is None:
                    # Pool empty before the first attempt: pending manual workflow.
                    result.reason = decision.reason
                    _log_call(db, tenant_id=tenant_id, task=task, provider="-", model="-",
                              status="PENDING_MANUAL", latency_ms=0, prompt_hash=prompt_hash,
                              error=decision.reason)
                    return result
                result.reason = decision.reason
                break

            product = db.get(ProviderProduct, decision.provider_product_id)
            account = db.get(ProviderAccount, product.account_id)
            # v5.3.2 §6 quality floor: a provider whose latest fresh benchmark
            # failed this task is not eligible for it — skip and fail over.
            gate_reason = benchmark_gate(db, product.id, task)
            if gate_reason:
                reason = f"{account.provider}: {gate_reason}"
                result.attempts.append(
                    {"provider": account.provider, "status": "SKIPPED", "reason": reason}
                )
                result.reason = reason
                record_audit(
                    db, tenant_id=tenant_id, actor_type="SYSTEM", actor_id="llm-gateway",
                    action="llm.skipped", resource_type="provider_product",
                    resource_id=str(product.id), payload={"reason": reason, "task": task},
                )
                exclude.append(product.id)
                continue
            adapter = ADAPTERS.get(account.provider)
            api_key = _provider_key(account.provider, settings)
            if adapter is None or not api_key:
                reason = (
                    f"no HTTP adapter for '{account.provider}'"
                    if adapter is None
                    else f"no API key configured for '{account.provider}' (settings)"
                )
                result.attempts.append({"provider": account.provider, "status": "SKIPPED", "reason": reason})
                record_audit(
                    db, tenant_id=tenant_id, actor_type="SYSTEM", actor_id="llm-gateway",
                    action="llm.skipped", resource_type="provider_product",
                    resource_id=str(product.id), payload={"reason": reason},
                )
                exclude.append(product.id)
                continue

            resolved_model = model or _default_model(account.provider)
            started = time.monotonic()
            try:
                text = adapter(prompt, model or "", api_key, settings, client)
                latency_ms = int((time.monotonic() - started) * 1000)
                result = LLMResult(
                    status="SUCCEEDED",
                    text=text,
                    provider=account.provider,
                    model=resolved_model,
                    latency_ms=latency_ms,
                    attempts=result.attempts
                    + [{"provider": account.provider, "status": "SUCCEEDED"}],
                )
                _log_call(db, tenant_id=tenant_id, task=task, provider=account.provider,
                          model=resolved_model, status="SUCCEEDED", latency_ms=latency_ms,
                          prompt_hash=prompt_hash)
                record_audit(
                    db, tenant_id=tenant_id, actor_type="SYSTEM", actor_id="llm-gateway",
                    action="llm.succeeded", resource_type="provider_product",
                    resource_id=str(product.id),
                    payload={"provider": account.provider, "model": resolved_model,
                             "latency_ms": latency_ms, "task": task},
                )
                return result
            except LLMProviderError as exc:
                latency_ms = int((time.monotonic() - started) * 1000)
                result.attempts.append(
                    {"provider": account.provider, "status": "FAILED", "reason": str(exc)}
                )
                _log_call(db, tenant_id=tenant_id, task=task, provider=account.provider,
                          model=resolved_model, status="FAILED", latency_ms=latency_ms,
                          prompt_hash=prompt_hash, error=str(exc))
                if not exc.retryable or attempts_left == 0:
                    result.status = "FAILED"
                    result.reason = str(exc)
                    return result
                # v5.3.2 §3 step 14 / §11: exhaust the free pool before stopping.
                record_audit(
                    db, tenant_id=tenant_id, actor_type="SYSTEM", actor_id="llm-gateway",
                    action="llm.failover", resource_type="provider_product",
                    resource_id=str(product.id),
                    payload={"from_provider": account.provider, "reason": str(exc), "task": task},
                )
                exclude.append(product.id)

        if result.status != "SUCCEEDED":
            result.status = result.status or "FAILED"
        return result
    finally:
        if own_client:
            client.close()


def _default_model(provider: str) -> str:
    return {
        "groq": "openai/gpt-oss-20b",  # namespaced ids after llama-default retirement (2026-11)
        "github_models": "openai/gpt-4o-mini",
        "gemini": "gemini-3.8-flash",  # 2.5-flash retired for new users (2026-11)
        "cloudflare_workers_ai": "@cf/meta/llama-3.1-8b-instruct",
        "openrouter": "inclusionai/ling-3.2-flash:free",
        "mistral": "mistral-small-latest",
        "indictrans2": "indictrans2-dist-200M",
    }.get(provider, provider)
