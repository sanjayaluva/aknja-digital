"""Telegram notification outbox (docs/39 reliability, round T-006).

Pins the docs/39 contract: durable idempotent enqueue, provider-confirmed
delivery only on 200/ok, exponential backoff honoring retry_after, terminal
failure on definitive rejection, unconfigured channel loses nothing, and the
three platform hooks (approval requested, quota hard-stop, AI run parked).
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.enums import AgentRunState, ProviderCategory
from app.modules.governance.service import create_approval_request
from app.modules.ops.models import NotificationOutbox
from app.modules.ops.notifications import (
    MAX_ATTEMPTS,
    _next_delay_s,
    enqueue_notification,
    notify_admin,
    process_outbox,
)
from app.modules.resources.service import admit_usage
from tests.test_ai_inference import _mock_client
from tests.test_orchestrator_llm import _capability, _principal
from tests.test_quota import setup_product


def _settings(**overrides) -> Settings:
    base = {
        "telegram_bot_token": "bot-test-token",
        "telegram_admin_chat_id": "424242",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _rows(db) -> list[NotificationOutbox]:
    return list(db.scalars(select(NotificationOutbox)).all())


# --- enqueue semantics -------------------------------------------------------


def test_enqueue_renders_both_languages_with_ref_footer(db, seed) -> None:
    ml = enqueue_notification(
        db, template_key="run.blocked", language="ml",
        payload={"objective": "Draft a brief", "reason": "no provider", "run_id": "r1"},
        idempotency_key="run.blocked:r1", tenant_id=seed.tenant.id,
    )
    en = enqueue_notification(
        db, template_key="run.blocked", language="en",
        payload={"objective": "Draft a brief", "reason": "no provider", "run_id": "r1"},
        idempotency_key="run.blocked:r1-en", tenant_id=seed.tenant.id,
    )
    assert "AI റൺ തടഞ്ഞു" in ml.body
    assert "AI run parked for review" in en.body
    assert ml.body.endswith("· ref run.blocked:r1")      # duplicate marker
    assert en.body.endswith("· ref un.blocked:r1-en")    # last 16 chars of the key


def test_enqueue_dedupes_on_idempotency_key(db, seed) -> None:
    first = notify_admin(
        db, template_key="system.test", payload={},
        idempotency_key="dup-key", tenant_id=seed.tenant.id,
    )
    second = notify_admin(
        db, template_key="system.test", payload={},
        idempotency_key="dup-key", tenant_id=seed.tenant.id,
    )
    assert first is not None and second is not None
    assert first.id == second.id
    assert len(_rows(db)) == 1


def test_unknown_template_rejected(db, seed) -> None:
    from app.core.errors import ConflictError

    with pytest.raises(ConflictError, match="Unknown notification template"):
        enqueue_notification(
            db, template_key="nope", payload={}, idempotency_key="k", tenant_id=seed.tenant.id
        )


def test_missing_template_field_rejected_at_enqueue(db, seed) -> None:
    from app.core.errors import ConflictError

    with pytest.raises(ConflictError, match="missing field"):
        enqueue_notification(
            db, template_key="run.blocked", payload={"objective": "x"},  # no reason/run_id
            idempotency_key="k2", tenant_id=seed.tenant.id,
        )


# --- delivery semantics ------------------------------------------------------


def test_process_sends_and_marks_sent(db, seed, monkeypatch) -> None:
    from app.modules.ops import notifications

    cfg = _settings()
    monkeypatch.setattr(notifications, "get_settings", lambda: cfg)
    row = notify_admin(
        db, template_key="system.test", payload={},
        idempotency_key="send-ok", tenant_id=seed.tenant.id,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.telegram.org"
        assert "/botbot-test-token/sendMessage" in str(request.url.path)
        body = request.read()
        assert b'"chat_id":"424242"' in body
        assert "ടെസ്റ്റ് സന്ദേശം".encode() in body  # ml default from seeded settings
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 531}})

    summary = process_outbox(db, http_client=_mock_client(handler), settings=cfg)
    db.commit()
    assert summary == {"due": 1, "sent": 1, "failed": 0, "retried": 0, "unconfigured": 0}
    assert row.status == "SENT"
    assert row.provider_message_id == "531"
    assert row.sent_at is not None
    assert row.attempts == 1


def test_rate_limit_schedules_retry_with_retry_after(db, seed, monkeypatch) -> None:
    from app.modules.ops import notifications

    cfg = _settings()
    monkeypatch.setattr(notifications, "get_settings", lambda: cfg)
    row = notify_admin(
        db, template_key="system.test", payload={},
        idempotency_key="rl-1", tenant_id=seed.tenant.id,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, json={"ok": False, "parameters": {"retry_after": 37}}
        )

    summary = process_outbox(db, http_client=_mock_client(handler), settings=cfg)
    db.commit()
    assert summary["retried"] == 1
    assert row.status == "PENDING"
    assert row.attempts == 1
    assert "rate limited" in row.last_error
    assert row.next_attempt_at is not None
    assert row.next_attempt_at > row.updated_at + timedelta(seconds=30)


def test_definitive_rejection_fails_terminal(db, seed, monkeypatch) -> None:
    from app.modules.ops import notifications

    cfg = _settings()
    monkeypatch.setattr(notifications, "get_settings", lambda: cfg)
    row = notify_admin(
        db, template_key="system.test", payload={},
        idempotency_key="term-1", tenant_id=seed.tenant.id,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})

    summary = process_outbox(db, http_client=_mock_client(handler), settings=cfg)
    summary2 = process_outbox(db, http_client=_mock_client(handler), settings=cfg)
    db.commit()
    assert summary["failed"] == 1
    assert summary2["due"] == 0  # terminal: never re-attempted
    assert row.status == "FAILED"
    assert "chat not found" in row.last_error
    assert row.attempts == 1


@pytest.mark.parametrize("status,description", [
    (401, "Unauthorized"),          # invalid token (seen in the CLI evidence run)
    (403, "Forbidden: bot was blocked"),
])
def test_unauthorized_and_blocked_are_terminal(db, seed, monkeypatch, status, description) -> None:
    from app.modules.ops import notifications

    cfg = _settings()
    monkeypatch.setattr(notifications, "get_settings", lambda: cfg)
    row = notify_admin(
        db, template_key="system.test", payload={},
        idempotency_key=f"term-{status}", tenant_id=seed.tenant.id,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"ok": False, "description": description})

    summary = process_outbox(db, http_client=_mock_client(handler), settings=cfg)
    db.commit()
    assert summary["failed"] == 1
    assert row.status == "FAILED"  # definitive: no backoff, no retry
    assert row.next_attempt_at is None


def test_unconfigured_channel_loses_nothing(db, seed, monkeypatch) -> None:
    from app.modules.ops import notifications

    cfg = _settings(telegram_bot_token="", telegram_admin_chat_id="")
    monkeypatch.setattr(notifications, "get_settings", lambda: cfg)
    row = notify_admin(
        db, template_key="system.test", payload={},
        idempotency_key="unconf-1", tenant_id=seed.tenant.id,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not egress when the channel is unconfigured")

    summary = process_outbox(db, http_client=_mock_client(handler), settings=cfg)
    db.commit()
    assert summary["unconfigured"] == 1
    assert row.status == "PENDING"
    assert row.attempts == 0


def test_max_attempts_marks_failed(db, seed, monkeypatch) -> None:
    from app.modules.ops import notifications

    cfg = _settings()
    monkeypatch.setattr(notifications, "get_settings", lambda: cfg)
    row = notify_admin(
        db, template_key="system.test", payload={},
        idempotency_key="max-1", tenant_id=seed.tenant.id,
    )
    row.attempts = MAX_ATTEMPTS - 1  # one uncertain attempt left

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"ok": False, "description": "bad gateway"})

    summary = process_outbox(db, http_client=_mock_client(handler), settings=cfg)
    db.commit()
    assert summary["failed"] == 1
    assert row.status == "FAILED"
    assert row.attempts == MAX_ATTEMPTS


def test_backoff_is_exponential_and_capped() -> None:
    assert _next_delay_s(1) == 120
    assert _next_delay_s(2) == 240
    assert _next_delay_s(3) == 480
    assert _next_delay_s(10) == 3600            # capped
    assert _next_delay_s(1, retry_after_s=37) == 37   # 429 retry_after wins
    assert _next_delay_s(1, retry_after_s=100_000) == 86_400  # retry_after capped at 24h


# --- platform hooks ----------------------------------------------------------


def test_approval_request_hook_enqueues_notification(db, seed) -> None:
    request = create_approval_request(
        db, tenant_id=seed.tenant.id, gate="production.deploy",
        title="Deploy client site", payload={"app": "portal"},
    )
    db.commit()
    rows = [r for r in _rows(db) if r.template_key == "approval.requested"]
    assert len(rows) == 1
    assert rows[0].approval_request_id == request.id
    assert request.nonce in rows[0].body
    assert "production.deploy" in rows[0].body


def test_quota_hard_stop_hook_enqueues_alert(db, seed) -> None:
    product = setup_product(db, seed.tenant.id, allowance=100, reported=94)
    decision = admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM,
        quantity=2, idempotency_key="hardstop-notify-1",
    )
    db.commit()
    assert decision.admitted is False
    assert "hard-stop" in decision.reason
    rows = [r for r in _rows(db) if r.template_key == "quota.hard_stop"]
    assert len(rows) == 1
    assert product.product_key in rows[0].body
    # idempotent per product per UTC day: a second rejection adds nothing
    admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM,
        quantity=2, idempotency_key="hardstop-notify-2",
    )
    db.commit()
    assert len([r for r in _rows(db) if r.template_key == "quota.hard_stop"]) == 1


def test_run_parked_hook_enqueues_alert(db, seed, monkeypatch) -> None:
    import app.modules.ai.inference as inference_module
    from app.modules.ai.orchestrator import create_run, execute_llm_step, transition_run
    from app.modules.ops import notifications
    from app.modules.resources.candidates import register_candidate_providers

    register_candidate_providers(db, seed.tenant.id)  # all FREE_UNVERIFIED
    inference_settings = Settings(_env_file=None, ai_provider_enabled=True)
    monkeypatch.setattr(inference_module, "get_settings", lambda: inference_settings)
    monkeypatch.setattr(
        notifications, "get_settings",
        lambda: _settings(telegram_bot_token="", telegram_admin_chat_id=""),
    )
    cap = _capability(db, seed)
    principal = _principal(seed)
    run = create_run(db, principal=principal, capability_id=cap.id, objective="summarize brief")
    transition_run(db, run=run, principal=principal, to_state=AgentRunState.PLAN)
    transition_run(db, run=run, principal=principal, to_state=AgentRunState.POLICY_CHECK)
    transition_run(db, run=run, principal=principal, to_state=AgentRunState.EXECUTE_LOW_RISK)
    db.commit()

    result = execute_llm_step(
        db, run=run, principal=principal, prompt="summarize",
        http_client=_mock_client(lambda r: httpx.Response(200, json={})),
    )
    db.commit()
    assert result["status"] == "PENDING_MANUAL"
    assert run.state == AgentRunState.BLOCKED.value
    rows = [r for r in _rows(db) if r.template_key == "run.blocked"]
    assert len(rows) == 1
    assert str(run.id) in rows[0].body
    assert "summarize brief" in rows[0].body
