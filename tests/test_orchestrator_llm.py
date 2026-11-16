"""Orchestrator LLM step integration (v5.3.2 §5C, docs/09 state machine).

A model response is never a completed action. These tests pin the contract:
- LLM steps only in PLAN / EXECUTE_LOW_RISK / EXECUTE_APPROVED;
- SUCCEEDED records event + audit and leaves the run in its execution state;
- PENDING_MANUAL parks the run for a human (BLOCKED; RETRY_WAIT when coming
  from EXECUTE_APPROVED, the closest legal state) — never a silent degrade;
- FAILED (provider exhaustion) parks in RETRY_WAIT;
- CONFIDENTIAL runs are blocked before any egress.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.core.enums import AgentRunState, DataClassification
from app.modules.ai.models import AgentCapability, AgentRunEvent
from app.modules.ai.orchestrator import (
    CAPABILITY_TASKS,
    create_run,
    execute_llm_step,
    seed_capabilities,
    transition_run,
)
from app.modules.governance.models import AuditEvent
from app.modules.identity.service import Principal
from app.modules.resources.candidates import register_candidate_providers
from tests.test_ai_inference import _mock_client, _settings, _verify_provider


def _principal(seed) -> Principal:
    return Principal(
        user_id=seed.admin.id, email=seed.admin.email, tenant_id=seed.tenant.id,
        role="SUPER_ADMIN", client_id=None, session_id=seed.admin.id, csrf_token="",
    )


# Legal state-machine paths from OBSERVE to each useful starting state.
PATHS = {
    AgentRunState.PLAN: [AgentRunState.PLAN],
    AgentRunState.POLICY_CHECK: [AgentRunState.PLAN, AgentRunState.POLICY_CHECK],
    AgentRunState.EXECUTE_LOW_RISK: [
        AgentRunState.PLAN, AgentRunState.POLICY_CHECK, AgentRunState.EXECUTE_LOW_RISK,
    ],
    AgentRunState.EXECUTE_APPROVED: [
        AgentRunState.PLAN, AgentRunState.POLICY_CHECK,
        AgentRunState.WAITING_APPROVAL, AgentRunState.EXECUTE_APPROVED,
    ],
}


def _capability(db, seed) -> AgentCapability:
    """Query the seeded capability (seed_capabilities returns only new rows)."""
    seed_capabilities(db, seed.tenant.id)
    return db.scalar(
        select(AgentCapability).where(
            AgentCapability.tenant_id == seed.tenant.id,
            AgentCapability.key == "planning_analyst",
        )
    )


def _run_in(db, seed, state: AgentRunState, classification: str = "INTERNAL"):
    cap = _capability(db, seed)
    principal = _principal(seed)
    run = create_run(
        db, principal=principal, capability_id=cap.id,
        objective="Draft requirements for a landing page",
        data_classification=classification,
    )
    for target in PATHS[state]:
        reason = "high-risk step needs approval" if target == AgentRunState.WAITING_APPROVAL else ""
        transition_run(db, run=run, principal=principal, to_state=target, reason=reason)
    db.commit()
    return run, principal


def test_llm_step_success_records_event_and_audit(db, seed, monkeypatch) -> None:
    register_candidate_providers(db, seed.tenant.id)
    _verify_provider(db, seed, "groq")
    run, principal = _run_in(db, seed, AgentRunState.EXECUTE_LOW_RISK)

    import app.modules.ai.inference as inference_module

    monkeypatch.setattr(inference_module, "get_settings", lambda: _settings())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.groq.com"
        # default task for planning_analyst is the requirements profile
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "## Requirements\n1. Hero section"}}]}
        )

    result = execute_llm_step(
        db, run=run, principal=principal, prompt="Draft requirements",
        http_client=_mock_client(handler),
    )
    db.commit()
    assert result["status"] == "SUCCEEDED"
    assert result["task"] == CAPABILITY_TASKS["planning_analyst"] == "requirements"
    assert result["provider"] == "groq"
    assert run.state == AgentRunState.EXECUTE_LOW_RISK.value  # model output is not a completion
    event = db.scalars(
        select(AgentRunEvent).where(AgentRunEvent.run_id == run.id)
    ).all()
    assert any("llm step succeeded: groq" in (e.reason or "") for e in event)
    audit = db.query(AuditEvent).filter(
        AuditEvent.action == "agent_run.llm_step"
    ).one()
    assert audit.resource_id == str(run.id)


def test_llm_step_parks_run_blocked_when_no_provider(db, seed, monkeypatch) -> None:
    register_candidate_providers(db, seed.tenant.id)  # all FREE_UNVERIFIED
    run, principal = _run_in(db, seed, AgentRunState.EXECUTE_LOW_RISK)

    import app.modules.ai.inference as inference_module

    monkeypatch.setattr(inference_module, "get_settings", lambda: _settings())

    result = execute_llm_step(
        db, run=run, principal=principal, prompt="summarize",
        http_client=_mock_client(lambda r: httpx.Response(200, json={})),
    )
    db.commit()
    assert result["status"] == "PENDING_MANUAL"
    assert "no eligible FREE_VERIFIED" in result["reason"]
    assert run.state == AgentRunState.BLOCKED.value  # founder review queue


def test_llm_step_parks_in_retry_wait_from_execute_approved(db, seed, monkeypatch) -> None:
    """BLOCKED is not reachable from EXECUTE_APPROVED; PENDING_MANUAL uses
    RETRY_WAIT, the closest legal parking state."""
    register_candidate_providers(db, seed.tenant.id)
    run, principal = _run_in(db, seed, AgentRunState.EXECUTE_APPROVED)
    assert run.state == AgentRunState.EXECUTE_APPROVED.value
    db.commit()

    import app.modules.ai.inference as inference_module

    monkeypatch.setattr(inference_module, "get_settings", lambda: _settings())

    result = execute_llm_step(
        db, run=run, principal=principal, prompt="summarize",
        http_client=_mock_client(lambda r: httpx.Response(200, json={})),
    )
    db.commit()
    assert result["status"] == "PENDING_MANUAL"
    assert run.state == AgentRunState.RETRY_WAIT.value


def test_llm_step_failed_provider_parks_retry_wait(db, seed, monkeypatch) -> None:
    register_candidate_providers(db, seed.tenant.id)
    _verify_provider(db, seed, "groq")
    run, principal = _run_in(db, seed, AgentRunState.EXECUTE_LOW_RISK)

    import app.modules.ai.inference as inference_module

    monkeypatch.setattr(inference_module, "get_settings", lambda: _settings())

    # 403 = non-retryable -> FAILED without exhausting other providers
    result = execute_llm_step(
        db, run=run, principal=principal, prompt="x",
        http_client=_mock_client(lambda r: httpx.Response(403, json={"error": "forbidden"})),
    )
    db.commit()
    assert result["status"] == "FAILED"
    assert run.state == AgentRunState.RETRY_WAIT.value


def test_llm_step_blocks_confidential_run(db, seed) -> None:
    run, principal = _run_in(db, seed, AgentRunState.EXECUTE_LOW_RISK,
                             classification=DataClassification.CONFIDENTIAL.value)
    from app.core.errors import PolicyBlockedError

    with pytest.raises(PolicyBlockedError, match="cannot be sent to an LLM"):
        execute_llm_step(
            db, run=run, principal=principal, prompt="secret brief",
            http_client=_mock_client(lambda r: httpx.Response(200, json={})),
        )
    db.commit()
    assert run.state == AgentRunState.BLOCKED.value


def test_llm_step_rejects_wrong_state(db, seed) -> None:
    cap = _capability(db, seed)
    principal = _principal(seed)
    run = create_run(db, principal=principal, capability_id=cap.id, objective="x")
    db.commit()
    from app.core.errors import ConflictError

    with pytest.raises(ConflictError, match="not allowed in state OBSERVE"):
        execute_llm_step(
            db, run=run, principal=principal, prompt="x",
            http_client=_mock_client(lambda r: httpx.Response(200, json={})),
        )
