"""Governance services: hash-chained audit ledger and HITL approvals.

Invariants enforced here (protected governance):
- audit events are append-only and each entry chains to the previous hash;
- an approver can never approve a request they created;
- SYSTEM_WORKER principals can never approve anything;
- an approval only matches the exact payload hash it was issued for.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthorizationError, ConflictError, NotFoundError, PolicyBlockedError
from app.core.security import canonical_payload_hash, generate_token, utcnow
from app.modules.governance.models import (
    ApprovalDecision,
    ApprovalRequest,
    AuditEvent,
    EmergencyStop,
)
from app.modules.identity.service import Principal

GENESIS_HASH = "0" * 64


def record_audit(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    actor_type: str,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str = "",
    payload: dict | None = None,
    payload_hash: str = "",
) -> AuditEvent:
    """Append an immutable, hash-chained audit event."""
    payload = payload or {}
    if not payload_hash:
        payload_hash = canonical_payload_hash(payload)
    # Serialize chain appends: without this lock, two concurrent record_audit
    # transactions (e.g. parallel benchmark runs, observed live 2026-11-15)
    # both read the same tail and fork the hash chain → every later drill
    # fails verify_audit_chain. READ COMMITTED + xact-scoped lock makes each
    # append see the previous commit.
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": 813501})
    prev = db.scalar(
        select(AuditEvent.entry_hash).order_by(AuditEvent.id.desc()).limit(1)
    )
    prev_hash = prev or GENESIS_HASH
    import hashlib
    import json

    canonical = json.dumps(
        {
            "prev_hash": prev_hash,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "actor_type": actor_type,
            "actor_id": str(actor_id),
            "action": action,
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "payload_hash": payload_hash,
            "metadata": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    entry_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    event = AuditEvent(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=str(actor_id),
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        payload_hash=payload_hash,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        metadata_=payload,
    )
    db.add(event)
    db.flush()
    return event


def verify_audit_chain(db: Session, limit: int | None = None) -> bool:
    """Recompute the chain to detect tampering (used by tests + admin UI).

    Checks both linkage (prev_hash chaining) and content integrity
    (recomputed entry hash per event).
    """
    import hashlib
    import json

    stmt = select(AuditEvent).order_by(AuditEvent.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    prev_hash = GENESIS_HASH
    for event in db.scalars(stmt):
        if event.prev_hash != prev_hash:
            return False
        canonical = json.dumps(
            {
                "prev_hash": event.prev_hash,
                "tenant_id": str(event.tenant_id) if event.tenant_id else None,
                "actor_type": event.actor_type,
                "actor_id": str(event.actor_id),
                "action": event.action,
                "resource_type": event.resource_type,
                "resource_id": str(event.resource_id),
                "payload_hash": event.payload_hash,
                "metadata": event.metadata_,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if event.entry_hash != expected:
            return False
        prev_hash = event.entry_hash
    return True


def create_approval_request(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    gate: str,
    title: str,
    payload: dict,
    requested_by_type: str = "USER",
    requested_by_id: str = "",
    summary_ml: str = "",
    ttl_hours: int | None = None,
) -> ApprovalRequest:
    settings = get_settings()
    request = ApprovalRequest(
        tenant_id=tenant_id,
        gate=gate,
        title=title,
        requested_by_type=requested_by_type,
        requested_by_id=str(requested_by_id),
        payload=payload,
        payload_hash=canonical_payload_hash(payload),
        nonce=generate_token("apr_"),
        expires_at=utcnow()
        + timedelta(hours=ttl_hours or settings.approval_default_expiry_hours),
        summary_ml=summary_ml,
    )
    db.add(request)
    db.flush()
    record_audit(
        db,
        tenant_id=tenant_id,
        actor_type=requested_by_type,
        actor_id=str(requested_by_id),
        action="approval.requested",
        resource_type="approval_request",
        resource_id=str(request.id),
        payload={"gate": gate, "payload_hash": request.payload_hash, "title": title},
    )
    # Founder alert (docs/39): durable outbox, idempotent by approval id.
    from app.modules.ops.notifications import notify_admin

    notify_admin(
        db,
        template_key="approval.requested",
        payload={
            "title": title,
            "gate": gate,
            "expires_at": request.expires_at.isoformat(),
            "nonce": request.nonce,
        },
        idempotency_key=f"approval.requested:{request.id}",
        tenant_id=tenant_id,
        approval_request_id=request.id,
    )
    return request


def decide_approval_request(
    db: Session,
    *,
    request: ApprovalRequest,
    principal: Principal,
    decision: str,
    note: str = "",
    payload_hash_to_verify: str | None = None,
) -> ApprovalRequest:
    if decision not in ("APPROVED", "REJECTED"):
        raise ConflictError("decision must be APPROVED or REJECTED")
    if not request.is_pending:
        raise ConflictError(f"Request already decided ({request.status})")
    if utcnow() > request.expires_at:
        request.status = "EXPIRED"
        db.flush()
        raise ConflictError("Request has expired")
    # --- Protected: no self-approval, no SYSTEM_WORKER approver. ---
    if principal.role.value == "SYSTEM_WORKER":
        raise AuthorizationError("System workers cannot approve requests")
    if not principal.can_approve:
        raise AuthorizationError("Role not allowed to approve")
    if (
        request.requested_by_type == "USER"
        and str(principal.user_id) == request.requested_by_id
    ):
        raise AuthorizationError("Self-approval is not permitted")
    if payload_hash_to_verify is not None and payload_hash_to_verify != request.payload_hash:
        raise PolicyBlockedError("Payload hash mismatch — approval is bound to a different payload")

    request.status = decision
    request.decided_at = utcnow()
    request.decided_by = principal.user_id
    db.add(
        ApprovalDecision(
            request_id=request.id,
            decision=decision,
            decided_by=principal.user_id,
            decided_by_type="USER",
            note=note,
            payload_hash_verified=payload_hash_to_verify is not None,
        )
    )
    db.flush()
    record_audit(
        db,
        tenant_id=request.tenant_id,
        actor_type="USER",
        actor_id=str(principal.user_id),
        action=f"approval.{decision.lower()}",
        resource_type="approval_request",
        resource_id=str(request.id),
        payload={"gate": request.gate, "note": note},
    )
    return request


def get_pending_approvals(db: Session, tenant_id: uuid.UUID) -> list[ApprovalRequest]:
    return list(
        db.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.status == "PENDING",
            )
            .order_by(ApprovalRequest.created_at.desc())
        )
    )


# --- Emergency stop (backlog B5) ---


def get_emergency_stop(db: Session) -> EmergencyStop:
    row = db.get(EmergencyStop, 1)
    if row is None:
        row = EmergencyStop(id=1, state="CLEAR")
        db.add(row)
        db.flush()
    return row


def set_emergency_stop(
    db: Session, *, principal: Principal, state: str, reason: str
) -> EmergencyStop:
    if principal.role.value not in ("SUPER_ADMIN",):
        raise AuthorizationError("Only the Super Admin can control the emergency stop")
    if state not in ("CLEAR", "SOFT", "HARD"):
        raise ConflictError("state must be CLEAR, SOFT or HARD")
    row = get_emergency_stop(db)
    row.state = state
    row.reason = reason
    if state == "CLEAR":
        row.cleared_at = utcnow()
        row.engaged_at = None
        row.engaged_by = None
    else:
        row.engaged_at = utcnow()
        row.engaged_by = principal.user_id
        row.cleared_at = None
    db.flush()
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        actor_type="USER",
        actor_id=str(principal.user_id),
        action=f"emergency_stop.{state.lower()}",
        resource_type="emergency_stop",
        resource_id="1",
        payload={"reason": reason},
    )
    return row


def assert_not_hard_stopped(db: Session) -> None:
    """Mutating API operations are refused while a HARD stop is engaged."""
    row = db.get(EmergencyStop, 1)
    if row is not None and row.state == "HARD":
        raise PolicyBlockedError(
            "Emergency stop (HARD) is engaged — mutating operations are paused",
            details={"reason": row.reason},
        )


def install_audit_immutability_trigger(db: Session) -> None:
    """Database-level guard: audit_events is append-only.

    UPDATE/DELETE raise unless the session explicitly sets
    `aknja.audit_admin = 'on'` (founder-only correction escape hatch).
    """
    db.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION aknja_audit_append_only() RETURNS trigger AS $$
            BEGIN
                IF current_setting('aknja.audit_admin', true) = 'on' THEN
                    IF TG_OP = 'DELETE' THEN
                        RETURN OLD;
                    END IF;
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'audit_events is append-only';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    db.execute(
        text(
            """
            DROP TRIGGER IF EXISTS trg_audit_append_only ON audit_events;
            CREATE TRIGGER trg_audit_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION aknja_audit_append_only();
            """
        )
    )
    db.commit()


def fetch_approval(db: Session, tenant_id: uuid.UUID, approval_id: uuid.UUID) -> ApprovalRequest:
    request = db.get(ApprovalRequest, approval_id)
    if request is None or request.tenant_id != tenant_id:
        raise NotFoundError("Approval request not found")
    return request
