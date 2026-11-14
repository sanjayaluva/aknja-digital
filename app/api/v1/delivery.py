"""Delivery API: projects, requirements, milestones, tasks, feedback, UAT."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CsrfDep, CurrentPrincipal, DbDep, WritePrincipal
from app.core.enums import (
    HostingMode,
    ProjectLifecycleState,
    TaskStatus,
)
from app.modules.delivery import service as delivery

router = APIRouter(tags=["delivery"])


class ProjectCreate(BaseModel):
    client_id: uuid.UUID
    name: str = Field(min_length=3, max_length=200)
    description: str = ""
    hosting_mode: HostingMode = HostingMode.CLIENT_OWNED
    contract_id: uuid.UUID | None = None


class ProjectTransition(BaseModel):
    to_state: ProjectLifecycleState


class RequirementCreate(BaseModel):
    title: str = Field(min_length=3)
    detail: str = ""
    in_scope: bool = True


class MilestoneCreate(BaseModel):
    title: str = Field(min_length=3)
    weight_pct: int = Field(ge=1, le=100)
    amount_minor: int = 0
    currency: str = "INR"


class TaskCreate(BaseModel):
    title: str = Field(min_length=3)
    description: str = ""
    milestone_id: uuid.UUID | None = None
    priority: str = "MEDIUM"
    estimate_hours: int = 0
    idempotency_key: str | None = None


class TaskTransition(BaseModel):
    to_status: TaskStatus
    actual_hours: int | None = None


class StagingPreviewCreate(BaseModel):
    url: str
    ttl_hours: int = 72


class FeedbackCreate(BaseModel):
    kind: str
    message: str = Field(min_length=3)
    page_or_module: str = ""
    severity: str = "LOW"
    reproduction_steps: str = ""


class FeedbackResolve(BaseModel):
    note: str
    status: str = "RESOLVED"


class UATDecision(BaseModel):
    checklist: list[dict]
    decision: str
    notes: str = ""
    milestone_id: uuid.UUID | None = None


def _project_out(p) -> dict:
    return {
        "id": str(p.id), "name": p.name, "client_id": str(p.client_id),
        "lifecycle_state": p.lifecycle_state, "hosting_mode": p.hosting_mode,
        "description": p.description,
    }


@router.get("/projects")
def list_projects(db: DbDep, principal: CurrentPrincipal, state: str | None = None) -> list[dict]:
    return [_project_out(p) for p in delivery.list_projects(db, principal.tenant_id, state)]


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep) -> dict:
    project = delivery.create_project(
        db,
        principal=principal,
        client_id=body.client_id,
        name=body.name,
        description=body.description,
        hosting_mode=body.hosting_mode.value,
        contract_id=body.contract_id,
    )
    return _project_out(project)


@router.get("/projects/{project_id}")
def get_project(project_id: uuid.UUID, db: DbDep, principal: CurrentPrincipal) -> dict:
    project = delivery.get_project(db, principal.tenant_id, project_id)
    out = _project_out(project)
    out["progress"] = delivery.milestone_progress(db, project.id)
    return out


@router.post("/projects/{project_id}/transition")
def transition_project(
    project_id: uuid.UUID, body: ProjectTransition, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    return _project_out(
        delivery.transition_project(
            db, tenant_id=principal.tenant_id, project_id=project_id, to_state=body.to_state
        )
    )


@router.post("/projects/{project_id}/requirements", status_code=201)
def add_requirement(
    project_id: uuid.UUID, body: RequirementCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    req = delivery.add_requirement(
        db, tenant_id=principal.tenant_id, project_id=project_id, title=body.title, detail=body.detail, in_scope=body.in_scope
    )
    return {"id": str(req.id), "title": req.title, "in_scope": req.in_scope}


@router.post("/projects/{project_id}/milestones", status_code=201)
def add_milestone(
    project_id: uuid.UUID, body: MilestoneCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    m = delivery.add_milestone(
        db, tenant_id=principal.tenant_id, project_id=project_id, title=body.title,
        weight_pct=body.weight_pct, amount_minor=body.amount_minor, currency=body.currency,
    )
    return {"id": str(m.id), "title": m.title, "weight_pct": m.weight_pct, "status": m.status}


@router.post("/projects/{project_id}/tasks", status_code=201)
def create_task(
    project_id: uuid.UUID, body: TaskCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    task = delivery.create_task(
        db, tenant_id=principal.tenant_id, project_id=project_id, title=body.title,
        description=body.description, milestone_id=body.milestone_id,
        priority=body.priority, estimate_hours=body.estimate_hours,
        idempotency_key=body.idempotency_key,
    )
    return {"id": str(task.id), "title": task.title, "status": task.status}


@router.post("/tasks/{task_id}/transition")
def transition_task(
    task_id: uuid.UUID, body: TaskTransition, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    task = delivery.transition_task(
        db, tenant_id=principal.tenant_id, task_id=task_id, to_status=body.to_status,
        actual_hours=body.actual_hours,
    )
    return {"id": str(task.id), "title": task.title, "status": task.status}


@router.post("/projects/{project_id}/staging-previews", status_code=201)
def create_staging_preview(
    project_id: uuid.UUID, body: StagingPreviewCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    preview, token = delivery.create_staging_preview(
        db, tenant_id=principal.tenant_id, project_id=project_id, url=body.url, ttl_hours=body.ttl_hours
    )
    return {"id": str(preview.id), "url": preview.url, "expires_at": preview.expires_at.isoformat(), "preview_token": token}


@router.post("/projects/{project_id}/feedback", status_code=201)
def submit_feedback(
    project_id: uuid.UUID, body: FeedbackCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    feedback = delivery.submit_feedback(
        db, principal=principal, project_id=project_id, kind=body.kind, message=body.message,
        page_or_module=body.page_or_module, severity=body.severity, reproduction_steps=body.reproduction_steps,
    )
    return {"id": str(feedback.id), "kind": feedback.kind, "status": feedback.status}


@router.post("/feedback/{feedback_id}/resolve")
def resolve_feedback(
    feedback_id: uuid.UUID, body: FeedbackResolve, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    feedback = delivery.resolve_feedback(
        db, tenant_id=principal.tenant_id, feedback_id=feedback_id, note=body.note, status=body.status
    )
    return {"id": str(feedback.id), "status": feedback.status}


@router.post("/projects/{project_id}/uat", status_code=201)
def record_uat(
    project_id: uuid.UUID, body: UATDecision, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    acceptance = delivery.record_uat_decision(
        db, principal=principal, project_id=project_id, checklist=body.checklist,
        decision=body.decision, notes=body.notes, milestone_id=body.milestone_id,
    )
    return {"id": str(acceptance.id), "decision": acceptance.decision}
