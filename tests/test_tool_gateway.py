"""Tool Gateway tests: allow-list, schema, classification, approvals,
idempotency, project scope (Phase 3 exit: bypass tests pass)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.enums import UserRole
from app.core.errors import AuthorizationError, ConflictError, NotFoundError, PolicyBlockedError
from app.modules.ai.gateway import ToolGateway, seed_builtin_tools
from app.modules.ai.orchestrator import create_run
from app.modules.crm import service as crm
from app.modules.governance import service as governance
from app.modules.identity.service import Principal
from tests.conftest import make_user


@pytest.fixture
def tools(db):
    seed_builtin_tools(db)
    db.commit()


def founder(seed) -> Principal:
    return Principal(
        user_id=seed.admin.id, email=seed.admin.email, tenant_id=seed.tenant.id,
        role=UserRole.SUPER_ADMIN, client_id=None, session_id=seed.admin.id, csrf_token="",
    )


def operator(seed, user) -> Principal:
    return Principal(
        user_id=user.id, email=user.email, tenant_id=seed.tenant.id,
        role=UserRole.INTERNAL_OPERATOR, client_id=None, session_id=user.id, csrf_token="",
    )


def test_execute_low_risk_tool(db, seed, tools) -> None:
    gw = ToolGateway(db)
    execution = gw.execute_tool(
        principal=founder(seed), tool_name="catalog.search",
        arguments={"query": "Playwright"}, idempotency_key="gw-1",
    )
    assert execution.status == "SUCCEEDED"
    assert execution.result["count"] >= 0


def test_unknown_tool_rejected(db, seed, tools) -> None:
    gw = ToolGateway(db)
    with pytest.raises(NotFoundError):
        gw.execute_tool(
            principal=founder(seed), tool_name="rm -rf", arguments={},
            idempotency_key="gw-2",
        )


def test_disabled_tool_blocked(db, seed, tools) -> None:
    from app.modules.ai.models import ToolDefinition

    tool = db.scalar(select(ToolDefinition).where(ToolDefinition.name == "catalog.search"))
    assert tool is not None
    tool.is_active = False
    db.flush()
    gw = ToolGateway(db)
    with pytest.raises(PolicyBlockedError):
        gw.execute_tool(
            principal=founder(seed), tool_name="catalog.search",
            arguments={"query": "x"}, idempotency_key="gw-3",
        )


def test_argument_schema_violation_blocked(db, seed, tools) -> None:
    gw = ToolGateway(db)
    with pytest.raises(ConflictError, match="schema"):
        gw.execute_tool(
            principal=founder(seed), tool_name="catalog.search",
            arguments={"unexpected": 1}, idempotency_key="gw-4",
        )


def test_restricted_data_classification_blocked(db, seed, tools) -> None:
    gw = ToolGateway(db)
    with pytest.raises(PolicyBlockedError, match="RESTRICTED"):
        gw.execute_tool(
            principal=founder(seed), tool_name="catalog.search",
            arguments={"query": "x", "data_classification": "RESTRICTED"},
            idempotency_key="gw-5",
        )


def test_idempotent_replay_returns_same_execution(db, seed, tools) -> None:
    gw = ToolGateway(db)
    first = gw.execute_tool(
        principal=founder(seed), tool_name="catalog.search",
        arguments={"query": "playwright"}, idempotency_key="replay-1",
    )
    assert first.status == "SUCCEEDED"
    # Replaying the same idempotency key returns the SAME record (no re-run).
    second = gw.execute_tool(
        principal=founder(seed), tool_name="catalog.search",
        arguments={"query": "playwright"}, idempotency_key="replay-1",
    )
    assert second.id == first.id


def test_high_risk_tool_requires_approval(db, seed, tools) -> None:
    """email.draft is HIGH risk: no approval → AWAITING_APPROVAL, never sent."""
    gw = ToolGateway(db)
    execution = gw.execute_tool(
        principal=founder(seed), tool_name="email.draft",
        arguments={"to_email": "client@example.com", "subject": "Status", "body": "Hello"},
        idempotency_key="gw-approval-1",
    )
    assert execution.status == "AWAITING_APPROVAL"
    assert execution.result == {}

    # Self-approval attempt: the requester cannot approve their own tool call.
    approval = governance.create_approval_request(
        db, tenant_id=seed.tenant.id, gate="TOOL_EXECUTION", title="Send email",
        payload={"to": "client@example.com"}, requested_by_id=str(seed.admin.id),
    )
    with pytest.raises(AuthorizationError, match="Self-approval"):
        governance.decide_approval_request(
            db, request=approval, principal=founder(seed), decision="APPROVED"
        )


def test_approved_tool_executes_only_with_matching_hash(db, seed, tools) -> None:
    operator_user = make_user(db, email="op-gw@example.com", password="OperatorPass#1",
                              tenant_id=seed.tenant.id, role=UserRole.INTERNAL_OPERATOR)
    db.commit()
    op = operator(seed, operator_user)
    gw = ToolGateway(db)
    args = {"to_email": "client@example.com", "subject": "Digest", "body": "Hi"}

    execution = gw.execute_tool(
        principal=op, tool_name="email.draft", arguments=args,
        idempotency_key="gw-approval-2",
    )
    assert execution.status == "AWAITING_APPROVAL"

    approval = governance.create_approval_request(
        db, tenant_id=seed.tenant.id, gate="TOOL_EXECUTION", title="Send digest",
        payload={"to": "client@example.com"}, requested_by_id=str(operator_user.id),
    )
    # Founder approves a DIFFERENT payload → hash mismatch blocks execution.
    governance.decide_approval_request(
        db, request=approval, principal=founder(seed), decision="APPROVED"
    )
    with pytest.raises(PolicyBlockedError, match="different payload"):
        gw.execute_tool(
            principal=op, tool_name="email.draft", arguments=args,
            approval_request_id=approval.id,
            approval_payload_hash="sha256-wrong-hash",
            idempotency_key="gw-approval-2-retry",
        )

    # Correct payload hash: approval bound to the exact tool arguments.
    from app.core.security import canonical_payload_hash

    approval2 = governance.create_approval_request(
        db, tenant_id=seed.tenant.id, gate="TOOL_EXECUTION", title="Send digest v2",
        payload=args, requested_by_id=str(operator_user.id),
    )
    governance.decide_approval_request(
        db, request=approval2, principal=founder(seed), decision="APPROVED"
    )
    # The gateway binds the approval hash to the tool arguments hash.
    args_hash = canonical_payload_hash(args)
    assert approval2.payload_hash == args_hash
    executed = gw.execute_tool(
        principal=op, tool_name="email.draft", arguments=args,
        approval_request_id=approval2.id, approval_payload_hash=approval2.payload_hash,
        idempotency_key="gw-approval-3",
    )
    assert executed.status == "SUCCEEDED"
    assert "outbox_id" in executed.result


def test_project_scope_enforced(db, seed, tools) -> None:
    """A tool referencing a project outside the tenant is blocked."""
    from app.modules.delivery.models import Project
    from tests.conftest import make_tenant

    other = make_tenant(db, "Other", "other-xyz")
    foreign = Project(tenant_id=other.id, client_id=_any_client(db, seed), name="Foreign")
    db.add(foreign)
    db.commit()

    gw = ToolGateway(db)
    with pytest.raises(AuthorizationError, match="not found in your tenant"):
        gw.execute_tool(
            principal=founder(seed), tool_name="project.summarize",
            arguments={"project_id": str(foreign.id)}, idempotency_key="gw-scope-1",
        )


def _any_client(db, seed):
    return crm.create_client(db, principal=founder(seed), display_name="ScopeCo").id


def test_tool_executions_audited(db, seed, tools) -> None:
    from app.modules.governance.models import AuditEvent

    gw = ToolGateway(db)
    gw.execute_tool(
        principal=founder(seed), tool_name="catalog.search",
        arguments={"query": "seo"}, idempotency_key="gw-audit-1",
    )
    actions = db.scalars(
        select(AuditEvent.action).where(AuditEvent.action.like("tool.%"))
    ).all()
    assert "tool.execute" in actions
    assert "tool.succeeded" in actions


def test_ai_run_cannot_complete_without_evidence(db, seed, tools) -> None:
    from app.core.enums import AgentRunState
    from app.modules.ai import orchestrator
    from app.modules.ai.models import AgentCapability

    capability = db.scalar(
        select(AgentCapability).where(AgentCapability.tenant_id == seed.tenant.id)
    )
    principal = founder(seed)
    run = create_run(db, principal=principal, capability_id=capability.id,
                     objective="Draft weekly report")
    for state in (AgentRunState.PLAN, AgentRunState.POLICY_CHECK,
                  AgentRunState.EXECUTE_LOW_RISK, AgentRunState.VERIFY,
                  AgentRunState.PERSIST):
        orchestrator.transition_run(db, run=run, principal=principal, to_state=state)
    with pytest.raises(PolicyBlockedError, match="verification evidence"):
        orchestrator.transition_run(
            db, run=run, principal=principal, to_state=AgentRunState.COMPLETED
        )
    orchestrator.add_verification_evidence(
        db, run=run, principal=principal, evidence={"checked_by": "test", "result": "ok"}
    )
    orchestrator.transition_run(db, run=run, principal=principal, to_state=AgentRunState.COMPLETED)


def test_illegal_run_transition_rejected(db, seed, tools) -> None:
    from app.core.enums import AgentRunState
    from app.modules.ai import orchestrator
    from app.modules.ai.models import AgentCapability

    capability = db.scalar(
        select(AgentCapability).where(AgentCapability.tenant_id == seed.tenant.id)
    )
    principal = founder(seed)
    run = create_run(db, principal=principal, capability_id=capability.id, objective="X objective")
    with pytest.raises(ConflictError, match="Illegal transition"):
        orchestrator.transition_run(
            db, run=run, principal=principal, to_state=AgentRunState.COMPLETED
        )


def test_emergency_stop_blocks_new_runs(db, seed, tools) -> None:
    from app.modules.ai.models import AgentCapability
    from app.modules.governance import service as governance

    governance.set_emergency_stop(db, principal=founder(seed), state="SOFT", reason="test")
    capability = db.scalar(
        select(AgentCapability).where(AgentCapability.tenant_id == seed.tenant.id)
    )
    with pytest.raises(PolicyBlockedError, match="Emergency stop"):
        create_run(db, principal=founder(seed), capability_id=capability.id, objective="Y objective")
