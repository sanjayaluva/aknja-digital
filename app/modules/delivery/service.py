"""Delivery service: project lifecycle, requirements, milestones, tasks,
feedback, UAT and staging previews (docs/08, docs/15)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import (
    FeedbackKind,
    FeedbackStatus,
    HostingMode,
    MilestoneStatus,
    ProjectLifecycleState,
    TaskStatus,
)
from app.core.errors import AuthorizationError, ConflictError, NotFoundError, ValidationAppError
from app.core.security import generate_token, hash_token, utcnow
from app.modules.delivery.models import (
    Artifact,
    Feedback,
    Milestone,
    Project,
    Requirement,
    StagingPreview,
    Task,
    UATAcceptance,
)
from app.modules.identity.service import Principal

# Project lifecycle machine (SRS v5.2 §5.1 + terminal states).
PROJECT_TRANSITIONS: dict[ProjectLifecycleState, set[ProjectLifecycleState]] = {
    ProjectLifecycleState.DISCOVERY: {
        ProjectLifecycleState.LEAD_QUALIFIED,
        ProjectLifecycleState.ARCHIVED,
    },
    ProjectLifecycleState.LEAD_QUALIFIED: {
        ProjectLifecycleState.PROPOSAL_APPROVED,
        ProjectLifecycleState.ARCHIVED,
    },
    ProjectLifecycleState.PROPOSAL_APPROVED: {
        ProjectLifecycleState.CONTRACT_SIGNED,
        ProjectLifecycleState.ARCHIVED,
    },
    ProjectLifecycleState.CONTRACT_SIGNED: {
        ProjectLifecycleState.ASSET_INTAKE,
        ProjectLifecycleState.BLOCKED_ON_CLIENT_KYC,
    },
    ProjectLifecycleState.ASSET_INTAKE: {
        ProjectLifecycleState.ARCHITECTURE_AND_WIREFRAME,
        ProjectLifecycleState.BLOCKED_ON_CLIENT_KYC,
    },
    ProjectLifecycleState.BLOCKED_ON_CLIENT_KYC: {ProjectLifecycleState.ASSET_INTAKE},
    ProjectLifecycleState.ARCHITECTURE_AND_WIREFRAME: {
        ProjectLifecycleState.DEVELOPMENT_SPRINT,
    },
    ProjectLifecycleState.DEVELOPMENT_SPRINT: {
        ProjectLifecycleState.QA_AND_SECURITY_GATE,
    },
    ProjectLifecycleState.QA_AND_SECURITY_GATE: {
        ProjectLifecycleState.STAGING_UAT,
        ProjectLifecycleState.DEVELOPMENT_SPRINT,
    },
    ProjectLifecycleState.STAGING_UAT: {
        ProjectLifecycleState.PRODUCTION_HANDOFF,
        ProjectLifecycleState.DEVELOPMENT_SPRINT,
    },
    ProjectLifecycleState.PRODUCTION_HANDOFF: {
        ProjectLifecycleState.WARRANTY_AND_AMC,
    },
    ProjectLifecycleState.WARRANTY_AND_AMC: {
        ProjectLifecycleState.CLOSED,
    },
    ProjectLifecycleState.CLOSED: {ProjectLifecycleState.ARCHIVED},
    ProjectLifecycleState.ARCHIVED: set(),
}


def create_project(
    db: Session,
    *,
    principal: Principal,
    client_id: uuid.UUID,
    name: str,
    description: str = "",
    hosting_mode: str = HostingMode.CLIENT_OWNED.value,
    contract_id: uuid.UUID | None = None,
) -> Project:
    from app.modules.crm.service import get_client

    client = get_client(db, principal.tenant_id, client_id)
    project = Project(
        tenant_id=principal.tenant_id,
        client_id=client.id,
        contract_id=contract_id,
        name=name,
        slug=generate_token("")[:10],
        description=description,
        hosting_mode=hosting_mode,
        environment_key=f"proj-{generate_token('')[:8]}",
    )
    db.add(project)
    db.flush()
    return project


def get_project(db: Session, tenant_id: uuid.UUID, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.tenant_id != tenant_id:
        raise NotFoundError("Project not found")
    return project


def list_projects(
    db: Session, tenant_id: uuid.UUID, state: str | None = None
) -> list[Project]:
    stmt = select(Project).where(Project.tenant_id == tenant_id)
    if state:
        stmt = stmt.where(Project.lifecycle_state == state)
    return list(db.scalars(stmt.order_by(Project.created_at.desc())))


def transition_project(
    db: Session, *, tenant_id: uuid.UUID, project_id: uuid.UUID, to_state: ProjectLifecycleState
) -> Project:
    project = get_project(db, tenant_id, project_id)
    current = ProjectLifecycleState(project.lifecycle_state)
    if to_state not in PROJECT_TRANSITIONS.get(current, set()):
        raise ConflictError(
            f"Illegal project transition {current.value} → {to_state.value}",
            details={"from": current.value, "to": to_state.value},
        )
    if to_state == ProjectLifecycleState.STAGING_UAT:
        # Gate: QA/security must be passed and a staging preview must exist.
        previews = db.scalars(
            select(StagingPreview).where(StagingPreview.project_id == project.id)
        ).all()
        if not any(p.is_active for p in previews):
            raise ConflictError("STAGING_UAT requires an active staging preview link")
    if to_state == ProjectLifecycleState.PRODUCTION_HANDOFF:
        acceptance = db.scalar(
            select(UATAcceptance).where(
                UATAcceptance.project_id == project.id, UATAcceptance.decision == "ACCEPTED"
            )
        )
        if acceptance is None:
            raise ConflictError("PRODUCTION_HANDOFF requires an accepted UAT record")
    project.lifecycle_state = to_state.value
    db.flush()
    return project


def add_requirement(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    title: str,
    detail: str = "",
    in_scope: bool = True,
) -> Requirement:
    project = get_project(db, tenant_id, project_id)
    req = Requirement(
        tenant_id=tenant_id, project_id=project.id, title=title, detail=detail, in_scope=in_scope
    )
    db.add(req)
    db.flush()
    return req


def add_milestone(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    title: str,
    weight_pct: int,
    amount_minor: int = 0,
    currency: str = "INR",
    due_date: datetime | None = None,
) -> Milestone:
    project = get_project(db, tenant_id, project_id)
    total = (
        db.query(Milestone)
        .filter(Milestone.project_id == project.id)
        .with_entities(Milestone.weight_pct)
    )
    if sum(m[0] for m in total) + weight_pct > 100:
        raise ValidationAppError("milestone weights cannot exceed 100% in total")
    milestone = Milestone(
        tenant_id=tenant_id,
        project_id=project.id,
        title=title,
        weight_pct=weight_pct,
        amount_minor=amount_minor,
        currency=currency,
        due_date=due_date,
    )
    db.add(milestone)
    db.flush()
    return milestone


def create_task(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    title: str,
    description: str = "",
    milestone_id: uuid.UUID | None = None,
    priority: str = "MEDIUM",
    estimate_hours: int = 0,
    idempotency_key: str | None = None,
) -> Task:
    project = get_project(db, tenant_id, project_id)
    if idempotency_key:
        existing = db.scalar(
            select(Task).where(
                Task.tenant_id == tenant_id, Task.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return existing
    task = Task(
        tenant_id=tenant_id,
        project_id=project.id,
        milestone_id=milestone_id,
        title=title,
        description=description,
        priority=priority,
        estimate_hours=estimate_hours,
        idempotency_key=idempotency_key,
    )
    db.add(task)
    db.flush()
    return task


TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.BACKLOG: {TaskStatus.SPECIFIED, TaskStatus.CANCELLED},
    TaskStatus.SPECIFIED: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {TaskStatus.REVIEW, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
    TaskStatus.BLOCKED: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
    TaskStatus.REVIEW: {TaskStatus.VERIFIED, TaskStatus.IN_PROGRESS},
    TaskStatus.VERIFIED: {TaskStatus.DONE},
    TaskStatus.DONE: set(),
    TaskStatus.CANCELLED: set(),
}


def transition_task(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
    to_status: TaskStatus,
    actual_hours: int | None = None,
) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.tenant_id != tenant_id:
        raise NotFoundError("Task not found")
    current = TaskStatus(task.status)
    if to_status not in TASK_TRANSITIONS.get(current, set()):
        raise ConflictError(
            f"Illegal task transition {current.value} → {to_status.value}",
        )
    if to_status == TaskStatus.DONE:
        # No COMPLETED without independent verification (VERIFIED step).
        if current != TaskStatus.VERIFIED:
            raise ConflictError("Tasks must pass REVIEW → VERIFIED before DONE")
        task.completed_at = utcnow()
    if actual_hours is not None:
        task.actual_hours = actual_hours
    task.status = to_status.value
    db.flush()
    return task


def create_staging_preview(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    url: str,
    ttl_hours: int = 72,
) -> tuple[StagingPreview, str]:
    """Create an expiring, token-protected staging preview link."""
    project = get_project(db, tenant_id, project_id)
    token = generate_token("preview_")
    preview = StagingPreview(
        tenant_id=tenant_id,
        project_id=project.id,
        url=url,
        token_hash=hash_token(token),
        expires_at=utcnow() + timedelta(hours=ttl_hours),
    )
    db.add(preview)
    db.flush()
    return preview, token


def submit_feedback(
    db: Session,
    *,
    principal: Principal,
    project_id: uuid.UUID,
    kind: str,
    message: str,
    page_or_module: str = "",
    severity: str = "LOW",
    reproduction_steps: str = "",
) -> Feedback:
    project = get_project(db, principal.tenant_id, project_id)
    # Portal users may only submit feedback on their own client's projects.
    if principal.is_portal and project.client_id != principal.client_id:
        raise AuthorizationError("Project does not belong to your client account")
    if kind not in (k.value for k in FeedbackKind):
        raise ValidationAppError(f"Unknown feedback kind '{kind}'")
    feedback = Feedback(
        tenant_id=principal.tenant_id,
        project_id=project.id,
        submitted_by=principal.user_id,
        kind=kind,
        message=message,
        page_or_module=page_or_module,
        severity=severity,
        reproduction_steps=reproduction_steps,
    )
    db.add(feedback)
    db.flush()
    return feedback


def resolve_feedback(
    db: Session, *, tenant_id: uuid.UUID, feedback_id: uuid.UUID, note: str, status: str = "RESOLVED"
) -> Feedback:
    feedback = db.get(Feedback, feedback_id)
    if feedback is None or feedback.tenant_id != tenant_id:
        raise NotFoundError("Feedback not found")
    if status not in (s.value for s in FeedbackStatus):
        raise ValidationAppError(f"Unknown feedback status '{status}'")
    feedback.status = status
    feedback.resolution_note = note
    db.flush()
    return feedback


def record_uat_decision(
    db: Session,
    *,
    principal: Principal,
    project_id: uuid.UUID,
    checklist: list[dict],
    decision: str,
    notes: str = "",
    milestone_id: uuid.UUID | None = None,
) -> UATAcceptance:
    project = get_project(db, principal.tenant_id, project_id)
    # UAT acceptance must come from the client side (CLIENT_OWNER) or founder.
    if principal.is_portal:
        if project.client_id != principal.client_id:
            raise AuthorizationError("Project does not belong to your client account")
        if principal.role.value != "CLIENT_OWNER":
            raise AuthorizationError("Only the client owner can record UAT acceptance")
    if decision not in ("ACCEPTED", "REJECTED", "PENDING"):
        raise ValidationAppError("decision must be ACCEPTED, REJECTED or PENDING")
    acceptance = UATAcceptance(
        tenant_id=principal.tenant_id,
        project_id=project.id,
        milestone_id=milestone_id,
        checklist=checklist,
        decision=decision,
        decided_by=principal.user_id,
        decided_at=utcnow() if decision != "PENDING" else None,
        notes=notes,
    )
    db.add(acceptance)
    db.flush()
    return acceptance


def register_artifact(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    title: str,
    kind: str = "DOCUMENT",
    storage_key: str = "",
    content_type: str = "",
    size_bytes: int = 0,
    checksum: str = "",
    uploaded_by: uuid.UUID | None = None,
) -> Artifact:
    project = get_project(db, tenant_id, project_id)
    artifact = Artifact(
        tenant_id=tenant_id,
        project_id=project.id,
        kind=kind,
        title=title,
        storage_key=storage_key,
        content_type=content_type,
        size_bytes=size_bytes,
        checksum=checksum,
        uploaded_by=uploaded_by,
    )
    db.add(artifact)
    db.flush()
    return artifact


def milestone_progress(db: Session, project_id: uuid.UUID) -> dict:
    milestones = db.scalars(
        select(Milestone).where(Milestone.project_id == project_id)
    ).all()
    if not milestones:
        return {"total": 0, "done_weight": 0, "pct": 0}
    done_weight = sum(
        m.weight_pct
        for m in milestones
        if m.status in (MilestoneStatus.ACCEPTED.value, MilestoneStatus.PAID.value)
    )
    return {
        "total": len(milestones),
        "done_weight": done_weight,
        "pct": int(done_weight * 100 / max(1, sum(m.weight_pct for m in milestones))),
    }
