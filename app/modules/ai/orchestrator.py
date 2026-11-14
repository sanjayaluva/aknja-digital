"""Central AI Orchestrator — run state machine (docs/09, .aknja/workflows).

`OBSERVE → PLAN → POLICY_CHECK → EXECUTE_LOW_RISK / WAITING_APPROVAL →
EXECUTE_APPROVED → VERIFY → PERSIST → CONTINUE` plus terminal/exception
states. A model response is never a completed action: only Tool Gateway
results plus independent verification evidence move a run forward, and
nothing can be marked COMPLETED without verification evidence.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AgentRunState, DataClassification
from app.core.errors import AuthorizationError, ConflictError, NotFoundError, PolicyBlockedError
from app.core.security import utcnow
from app.modules.ai.models import AgentCapability, AgentRun, AgentRunEvent
from app.modules.governance.service import get_emergency_stop, record_audit
from app.modules.identity.service import Principal

# State machine edges (preconditions in code, audited on every transition).
TRANSITIONS: dict[AgentRunState, set[AgentRunState]] = {
    AgentRunState.OBSERVE: {AgentRunState.PLAN, AgentRunState.CANCELLED, AgentRunState.BLOCKED},
    AgentRunState.PLAN: {AgentRunState.POLICY_CHECK, AgentRunState.CANCELLED, AgentRunState.BLOCKED},
    AgentRunState.POLICY_CHECK: {
        AgentRunState.EXECUTE_LOW_RISK,
        AgentRunState.WAITING_APPROVAL,
        AgentRunState.BLOCKED,
        AgentRunState.CANCELLED,
    },
    AgentRunState.EXECUTE_LOW_RISK: {
        AgentRunState.VERIFY,
        AgentRunState.RETRY_WAIT,
        AgentRunState.QUARANTINED,
        AgentRunState.FAILED,
        AgentRunState.BLOCKED,
        AgentRunState.CANCELLED,
    },
    AgentRunState.WAITING_APPROVAL: {
        AgentRunState.EXECUTE_APPROVED,
        AgentRunState.BLOCKED,
        AgentRunState.CANCELLED,
    },
    AgentRunState.EXECUTE_APPROVED: {
        AgentRunState.VERIFY,
        AgentRunState.RETRY_WAIT,
        AgentRunState.QUARANTINED,
        AgentRunState.FAILED,
        AgentRunState.CANCELLED,
    },
    AgentRunState.VERIFY: {
        AgentRunState.PERSIST,
        AgentRunState.RETRY_WAIT,
        AgentRunState.QUARANTINED,
        AgentRunState.FAILED,
        AgentRunState.CANCELLED,
    },
    AgentRunState.PERSIST: {AgentRunState.CONTINUE, AgentRunState.COMPLETED, AgentRunState.CANCELLED},
    AgentRunState.CONTINUE: {AgentRunState.PLAN, AgentRunState.COMPLETED, AgentRunState.CANCELLED},
    AgentRunState.BLOCKED: {AgentRunState.PLAN, AgentRunState.CANCELLED},
    AgentRunState.RETRY_WAIT: {AgentRunState.PLAN, AgentRunState.CANCELLED, AgentRunState.FAILED},
    AgentRunState.QUARANTINED: {AgentRunState.CANCELLED},
    AgentRunState.ROLLBACK: {AgentRunState.CANCELLED, AgentRunState.FAILED},
    AgentRunState.FAILED: set(),
    AgentRunState.CANCELLED: set(),
    AgentRunState.COMPLETED: set(),
}

DEFAULT_CAPABILITIES = [
    ("planning_analyst", "Planning & Requirements Analyst", "Scope decomposition, estimates, risk lists."),
    ("software_engineer", "Software Engineering & Integration", "Implementation and integration tasks."),
    ("qa_security", "QA, Code Review & Security Verification", "Tests, reviews, security verification."),
    ("research_docs", "Research & Documentation", "Investigation and documentation drafts."),
    ("devops_recovery", "DevOps, Deployment & Recovery", "Deploy, smoke check, rollback support."),
    ("business_ops", "Business Operations & Client Communication", "Operational coordination and drafts."),
    ("ui_ux_creative", "UI/UX and Creative Production", "Wireframes and creative assets."),
    ("digital_marketing", "Digital Marketing and SEO", "Marketing workflows and content."),
    ("analytics_cro", "Analytics and CRO", "Measurement plans and experiments."),
    ("support_maintenance", "Support and Maintenance", "Tickets, incidents, maintenance tasks."),
]


def seed_capabilities(db: Session, tenant_id: uuid.UUID) -> list[AgentCapability]:
    from app.core.security import generate_token  # noqa: F401 — kept for parity with future runs

    existing = {
        c.key for c in db.scalars(select(AgentCapability).where(AgentCapability.tenant_id == tenant_id))
    }
    created = []
    for key, name, description in DEFAULT_CAPABILITIES:
        if key in existing:
            continue
        created.append(
            AgentCapability(
                tenant_id=tenant_id,
                key=key,
                name=name,
                description=description,
                allowed_tools=["catalog.search", "project.summarize", "artifact.register", "email.draft"],
                allowed_data_classes=[DataClassification.INTERNAL.value, DataClassification.PUBLIC.value],
            )
        )
        db.add(created[-1])
    db.flush()
    return created


def create_run(
    db: Session,
    *,
    principal: Principal,
    capability_id: uuid.UUID,
    objective: str,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    plan: list | None = None,
    acceptance_criteria: list | None = None,
    data_classification: str = DataClassification.INTERNAL.value,
    budget_minutes: int = 30,
    idempotency_key: str | None = None,
) -> AgentRun:
    stop = get_emergency_stop(db)
    if stop.state in ("SOFT", "HARD"):
        raise PolicyBlockedError("Emergency stop is engaged — new AI runs are paused")
    capability = db.get(AgentCapability, capability_id)
    if capability is None or capability.tenant_id != principal.tenant_id:
        raise NotFoundError("Capability not found in your tenant")
    if not capability.is_active:
        raise ConflictError("Capability is not active")
    if idempotency_key:
        existing = db.scalar(select(AgentRun).where(AgentRun.idempotency_key == idempotency_key))
        if existing is not None:
            return existing
    run = AgentRun(
        tenant_id=principal.tenant_id,
        capability_id=capability_id,
        project_id=project_id,
        task_id=task_id,
        objective=objective,
        state=AgentRunState.OBSERVE.value,
        plan=plan or [],
        acceptance_criteria=acceptance_criteria or [],
        data_classification=data_classification,
        budget_minutes=min(budget_minutes, capability.max_budget_minutes),
        idempotency_key=idempotency_key,
        started_at=utcnow(),
    )
    db.add(run)
    db.flush()
    _record_event(db, run, "-", AgentRunState.OBSERVE.value, "run created", principal)
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        actor_type="USER",
        actor_id=str(principal.user_id),
        action="agent_run.created",
        resource_type="agent_run",
        resource_id=str(run.id),
        payload={"objective": objective, "capability_id": str(capability_id)},
    )
    return run


def transition_run(
    db: Session,
    *,
    run: AgentRun,
    principal: Principal,
    to_state: AgentRunState,
    reason: str = "",
    plan: list | None = None,
    verification_evidence: dict | None = None,
    result_summary: str | None = None,
) -> AgentRun:
    current = AgentRunState(run.state)
    if to_state not in TRANSITIONS.get(current, set()):
        raise ConflictError(
            f"Illegal transition {current.value} → {to_state.value}",
            details={"from": current.value, "to": to_state.value},
        )
    # --- Protected: no COMPLETED without independent verification evidence. ---
    if to_state == AgentRunState.COMPLETED and not run.verification_evidence:
        raise PolicyBlockedError(
            "Cannot complete a run without verification evidence",
        )
    # WAITING_APPROVAL must be entered from POLICY_CHECK with a reason.
    if to_state == AgentRunState.WAITING_APPROVAL and not reason:
        raise ConflictError("WAITING_APPROVAL requires a reason describing the approval need")

    run.state = to_state.value
    if plan is not None:
        run.plan = plan
    if verification_evidence is not None:
        run.verification_evidence = verification_evidence
    if result_summary is not None:
        run.result_summary = result_summary
    if to_state in (AgentRunState.COMPLETED, AgentRunState.FAILED, AgentRunState.CANCELLED):
        run.finished_at = utcnow()
    db.flush()
    _record_event(db, run, current.value, to_state.value, reason, principal)
    record_audit(
        db,
        tenant_id=run.tenant_id,
        actor_type="USER",
        actor_id=str(principal.user_id),
        action=f"agent_run.{to_state.value.lower()}",
        resource_type="agent_run",
        resource_id=str(run.id),
        payload={"from": current.value, "reason": reason},
    )
    return run


def _record_event(
    db: Session,
    run: AgentRun,
    from_state: str,
    to_state: str,
    reason: str,
    principal: Principal | None,
) -> None:
    from app.core.security import generate_token

    db.add(
        AgentRunEvent(
            run_id=run.id,
            from_state=from_state,
            to_state=to_state,
            actor_type="USER" if principal else "SYSTEM",
            actor_id=str(principal.user_id) if principal else "system",
            reason=reason,
            idempotency_key=generate_token("evt_")[:48],
        )
    )
    db.flush()


def get_run(db: Session, tenant_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    run = db.get(AgentRun, run_id)
    if run is None or run.tenant_id != tenant_id:
        raise NotFoundError("Run not found")
    return run


def list_runs(db: Session, tenant_id: uuid.UUID, limit: int = 50) -> list[AgentRun]:
    return list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.tenant_id == tenant_id)
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
        )
    )


def add_verification_evidence(
    db: Session, *, run: AgentRun, principal: Principal, evidence: dict
) -> AgentRun:
    """Independent verification is recorded by a human or independent check,
    never fabricated by the run itself."""
    if principal.role.value == "SYSTEM_WORKER":
        raise AuthorizationError("A system worker cannot provide verification evidence")
    run.verification_evidence = {**(run.verification_evidence or {}), **evidence}
    db.flush()
    record_audit(
        db,
        tenant_id=run.tenant_id,
        actor_type="USER",
        actor_id=str(principal.user_id),
        action="agent_run.evidence_added",
        resource_type="agent_run",
        resource_id=str(run.id),
    )
    return run
