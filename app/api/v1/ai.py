"""AI orchestration API: capabilities, runs, tool executions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CsrfDep, CurrentPrincipal, DbDep, WritePrincipal
from app.core.enums import AgentRunState, DataClassification
from app.modules.ai import orchestrator
from app.modules.ai.gateway import ToolGateway

router = APIRouter(tags=["ai"])


class RunCreate(BaseModel):
    capability_id: uuid.UUID
    objective: str = Field(min_length=5)
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    plan: list = []
    acceptance_criteria: list = []
    data_classification: DataClassification = DataClassification.INTERNAL
    budget_minutes: int = Field(default=30, ge=1, le=240)
    idempotency_key: str | None = None


class RunTransition(BaseModel):
    to_state: AgentRunState
    reason: str = ""
    plan: list | None = None
    verification_evidence: dict | None = None
    result_summary: str | None = None


class EvidenceAdd(BaseModel):
    evidence: dict


class ToolExecute(BaseModel):
    tool_name: str
    arguments: dict
    run_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    approval_request_id: uuid.UUID | None = None
    approval_payload_hash: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=128)


def _run_out(r) -> dict:
    return {
        "id": str(r.id), "objective": r.objective, "state": r.state,
        "capability_id": str(r.capability_id),
        "project_id": str(r.project_id) if r.project_id else None,
        "budget_minutes": r.budget_minutes,
        "has_verification_evidence": bool(r.verification_evidence),
        "result_summary": r.result_summary,
    }


def _tool_out(t) -> dict:
    return {
        "id": str(t.id), "tool_name": t.tool.name, "status": t.status,
        "arguments_hash": t.arguments_hash, "error": t.error,
        "result": t.result if t.status == "SUCCEEDED" else None,
    }


@router.get("/capabilities")
def list_capabilities(db: DbDep, principal: CurrentPrincipal) -> list[dict]:
    from sqlalchemy import select

    from app.modules.ai.models import AgentCapability

    rows = db.scalars(
        select(AgentCapability).where(AgentCapability.tenant_id == principal.tenant_id)
    )
    return [
        {"id": str(c.id), "key": c.key, "name": c.name, "is_active": c.is_active}
        for c in rows
    ]


@router.get("/agent-runs")
def list_runs(db: DbDep, principal: CurrentPrincipal) -> list[dict]:
    return [_run_out(r) for r in orchestrator.list_runs(db, principal.tenant_id)]


@router.post("/agent-runs", status_code=201)
def create_run(body: RunCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep) -> dict:
    run = orchestrator.create_run(
        db, principal=principal, capability_id=body.capability_id,
        objective=body.objective, project_id=body.project_id, task_id=body.task_id,
        plan=body.plan, acceptance_criteria=body.acceptance_criteria,
        data_classification=body.data_classification.value,
        budget_minutes=body.budget_minutes, idempotency_key=body.idempotency_key,
    )
    return _run_out(run)


@router.post("/agent-runs/{run_id}/transition")
def transition_run(
    run_id: uuid.UUID, body: RunTransition, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    run = orchestrator.get_run(db, principal.tenant_id, run_id)
    run = orchestrator.transition_run(
        db, run=run, principal=principal, to_state=body.to_state, reason=body.reason,
        plan=body.plan, verification_evidence=body.verification_evidence,
        result_summary=body.result_summary,
    )
    return _run_out(run)


@router.post("/agent-runs/{run_id}/evidence")
def add_evidence(
    run_id: uuid.UUID, body: EvidenceAdd, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    run = orchestrator.get_run(db, principal.tenant_id, run_id)
    run = orchestrator.add_verification_evidence(db, run=run, principal=principal, evidence=body.evidence)
    return _run_out(run)


@router.get("/tools")
def list_tools(db: DbDep, principal: CurrentPrincipal) -> list[dict]:
    gateway = ToolGateway(db)
    return [
        {
            "id": str(t.id), "name": t.name, "risk_class": t.risk_class,
            "requires_approval": t.requires_approval, "is_active": t.is_active,
        }
        for t in gateway.list_tools()
    ]


@router.post("/tools/execute")
def execute_tool(
    body: ToolExecute, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    gateway = ToolGateway(db)
    execution = gateway.execute_tool(
        principal=principal,
        tool_name=body.tool_name,
        arguments=body.arguments,
        run_id=body.run_id,
        project_id=body.project_id,
        approval_request_id=body.approval_request_id,
        approval_payload_hash=body.approval_payload_hash,
        idempotency_key=body.idempotency_key,
    )
    return _tool_out(execution)
