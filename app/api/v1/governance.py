"""Governance API: approvals, audit events, emergency stop, policy view."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CsrfDep, CurrentPrincipal, DbDep, WritePrincipal
from app.modules.governance import service as governance

router = APIRouter(tags=["governance"])


class ApprovalCreate(BaseModel):
    gate: str
    title: str = ""
    payload: dict = {}
    summary_ml: str = ""
    ttl_hours: int | None = None


class ApprovalDecide(BaseModel):
    decision: str  # APPROVED | REJECTED
    note: str = ""
    payload_hash_to_verify: str | None = None


class EmergencyStopSet(BaseModel):
    state: str
    reason: str = ""


def _approval_out(a) -> dict:
    return {
        "id": str(a.id), "gate": a.gate, "title": a.title, "status": a.status,
        "payload_hash": a.payload_hash, "requested_by_id": a.requested_by_id,
        "expires_at": a.expires_at.isoformat(), "summary_ml": a.summary_ml,
    }


@router.get("/approvals")
def list_approvals(db: DbDep, principal: CurrentPrincipal) -> list[dict]:
    return [_approval_out(a) for a in governance.get_pending_approvals(db, principal.tenant_id)]


@router.post("/approvals", status_code=201)
def create_approval(
    body: ApprovalCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    request = governance.create_approval_request(
        db,
        tenant_id=principal.tenant_id,
        gate=body.gate,
        title=body.title,
        payload=body.payload,
        requested_by_type="USER",
        requested_by_id=str(principal.user_id),
        summary_ml=body.summary_ml,
        ttl_hours=body.ttl_hours,
    )
    return _approval_out(request)


@router.post("/approvals/{approval_id}/decide")
def decide_approval(
    approval_id: uuid.UUID, body: ApprovalDecide, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    request = governance.fetch_approval(db, principal.tenant_id, approval_id)
    request = governance.decide_approval_request(
        db,
        request=request,
        principal=principal,
        decision=body.decision,
        note=body.note,
        payload_hash_to_verify=body.payload_hash_to_verify,
    )
    return _approval_out(request)


@router.get("/audit-events")
def list_audit_events(db: DbDep, principal: CurrentPrincipal, limit: int = 100) -> list[dict]:
    from sqlalchemy import select

    from app.modules.governance.models import AuditEvent

    if not principal.is_internal:
        from app.core.errors import AuthorizationError

        raise AuthorizationError("Audit trail is restricted to internal roles")
    rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == principal.tenant_id)
        .order_by(AuditEvent.id.desc())
        .limit(min(limit, 500))
    )
    return [
        {
            "id": e.id, "action": e.action, "actor_type": e.actor_type, "actor_id": e.actor_id,
            "resource_type": e.resource_type, "resource_id": e.resource_id,
            "payload_hash": e.payload_hash, "entry_hash": e.entry_hash,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows
    ]


@router.get("/audit-events/verify")
def verify_audit(db: DbDep, principal: CurrentPrincipal) -> dict:
    if not principal.is_internal:
        from app.core.errors import AuthorizationError

        raise AuthorizationError("Audit verification is restricted to internal roles")
    return {"chain_valid": governance.verify_audit_chain(db)}


@router.get("/emergency-stop")
def get_emergency_stop(db: DbDep, principal: CurrentPrincipal) -> dict:
    row = governance.get_emergency_stop(db)
    return {"state": row.state, "reason": row.reason}


@router.post("/emergency-stop")
def set_emergency_stop(
    body: EmergencyStopSet, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    row = governance.set_emergency_stop(db, principal=principal, state=body.state, reason=body.reason)
    return {"state": row.state, "reason": row.reason}
