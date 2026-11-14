"""Governance tests: audit chain immutability, approvals, emergency stop."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.enums import UserRole
from app.core.errors import AuthorizationError, ConflictError, PolicyBlockedError
from app.core.security import utcnow
from app.modules.governance import service as governance
from app.modules.identity.service import Principal
from tests.conftest import make_user


def principal_for(user, tenant_id, role=UserRole.INTERNAL_OPERATOR) -> Principal:
    return Principal(
        user_id=user.id, email=user.email, tenant_id=tenant_id, role=role,
        client_id=None, session_id=user.id, csrf_token="",
    )


def test_audit_chain_valid_and_detects_tampering(db, seed) -> None:
    governance.record_audit(db, tenant_id=seed.tenant.id, actor_type="USER",
                            actor_id="u1", action="a.b", resource_type="x", resource_id="1")
    governance.record_audit(db, tenant_id=seed.tenant.id, actor_type="USER",
                            actor_id="u1", action="c.d", resource_type="y", resource_id="2")
    db.commit()
    assert governance.verify_audit_chain(db) is True
    # Tamper directly with admin escape hatch, then verify detects it.
    db.execute(text("SET LOCAL aknja.audit_admin = 'on'"))
    db.execute(text("UPDATE audit_events SET action = 'tampered' WHERE id = 1"))
    db.execute(text("SET LOCAL aknja.audit_admin = 'off'"))
    db.commit()
    assert governance.verify_audit_chain(db) is False


def test_audit_update_delete_blocked_by_database(db, seed) -> None:
    governance.record_audit(db, tenant_id=seed.tenant.id, actor_type="USER",
                            actor_id="u1", action="x.y", resource_type="z", resource_id="1")
    db.commit()
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("DELETE FROM audit_events"))
        db.commit()
    db.rollback()
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("UPDATE audit_events SET action = 'hacked'"))
        db.commit()
    db.rollback()


def test_no_self_approval(db, seed) -> None:
    operator = make_user(db, email="op@example.com", password="OperatorPass#1",
                         tenant_id=seed.tenant.id, role=UserRole.INTERNAL_OPERATOR)
    db.commit()
    principal = principal_for(operator, seed.tenant.id)
    request = governance.create_approval_request(
        db, tenant_id=seed.tenant.id, gate="PRODUCTION_CUTOVER", title="Deploy v1",
        payload={"digest": "sha256:abc"}, requested_by_id=str(operator.id),
    )
    with pytest.raises(AuthorizationError, match="Self-approval"):
        governance.decide_approval_request(
            db, request=request, principal=principal, decision="APPROVED"
        )
    assert request.status == "PENDING"


def test_super_admin_can_approve_operator_request(db, seed) -> None:
    operator = make_user(db, email="op2@example.com", password="OperatorPass#1",
                         tenant_id=seed.tenant.id, role=UserRole.INTERNAL_OPERATOR)
    db.commit()
    request = governance.create_approval_request(
        db, tenant_id=seed.tenant.id, gate="STAGING_DELIVERABLE", title="Send staging link",
        payload={"url": "https://staging.example/preview"},
        requested_by_id=str(operator.id),
    )
    founder = principal_for(seed.admin, seed.tenant.id, role=UserRole.SUPER_ADMIN)
    decided = governance.decide_approval_request(
        db, request=request, principal=founder, decision="APPROVED", payload_hash_to_verify=request.payload_hash
    )
    assert decided.status == "APPROVED"
    # Second decision attempt → conflict (already decided).
    with pytest.raises(ConflictError):
        governance.decide_approval_request(db, request=request, principal=founder, decision="REJECTED")


def test_expired_approval_cannot_be_decided(db, seed) -> None:
    request = governance.create_approval_request(
        db, tenant_id=seed.tenant.id, gate="CAMPAIGN_LAUNCH", title="Launch ads",
        payload={"campaign": 1}, requested_by_id="someone-else",
    )
    # Force expiry.
    request.expires_at = utcnow() - timedelta(hours=1)
    db.flush()
    founder = principal_for(seed.admin, seed.tenant.id, role=UserRole.SUPER_ADMIN)
    with pytest.raises(ConflictError, match="expired"):
        governance.decide_approval_request(db, request=request, principal=founder, decision="APPROVED")


def test_payload_hash_mismatch_blocks_decision(db, seed) -> None:
    request = governance.create_approval_request(
        db, tenant_id=seed.tenant.id, gate="PRODUCTION_CUTOVER", title="Deploy",
        payload={"digest": "sha256:real"}, requested_by_id="req-1",
    )
    founder = principal_for(seed.admin, seed.tenant.id, role=UserRole.SUPER_ADMIN)
    with pytest.raises(PolicyBlockedError, match="(?i)payload hash"):
        governance.decide_approval_request(
            db, request=request, principal=founder, decision="APPROVED",
            payload_hash_to_verify="sha256:different-payload",
        )
    assert request.status == "PENDING"


def test_emergency_stop_blocks_and_clears(db, seed) -> None:
    founder = principal_for(seed.admin, seed.tenant.id, role=UserRole.SUPER_ADMIN)
    governance.set_emergency_stop(db, principal=founder, state="HARD", reason="incident")
    with pytest.raises(PolicyBlockedError):
        governance.assert_not_hard_stopped(db)
    governance.set_emergency_stop(db, principal=founder, state="CLEAR", reason="resolved")
    governance.assert_not_hard_stopped(db)  # no raise


def test_non_admin_cannot_set_emergency_stop(db, seed) -> None:
    operator = make_user(db, email="op3@example.com", password="OperatorPass#1",
                         tenant_id=seed.tenant.id, role=UserRole.INTERNAL_OPERATOR)
    db.commit()
    principal = principal_for(operator, seed.tenant.id)
    with pytest.raises(AuthorizationError):
        governance.set_emergency_stop(db, principal=principal, state="HARD", reason="nope")


def test_approval_api_flow(app, db, client, seed, admin_client) -> None:
    from tests.conftest import AuthClient

    make_user(db, email="api-op@example.com", password="OperatorPass#1",
              tenant_id=seed.tenant.id, role=UserRole.INTERNAL_OPERATOR)
    db.commit()
    operator = AuthClient(app, "api-op@example.com", "OperatorPass#1")

    # Operator requests; founder approves (no self-approval anywhere).
    create = operator.post(
        "/api/v1/approvals",
        json={"gate": "CLIENT_OUTBOUND_COMMS", "title": "Send status digest",
              "payload": {"to": "client@example.com"}},
    )
    assert create.status_code == 201
    approval_id = create.json()["id"]
    payload_hash = create.json()["payload_hash"]

    listed = admin_client.get("/api/v1/approvals")
    assert any(a["id"] == approval_id for a in listed.json())

    decide = admin_client.post(
        f"/api/v1/approvals/{approval_id}/decide",
        json={"decision": "APPROVED", "payload_hash_to_verify": payload_hash},
    )
    assert decide.status_code == 200
    assert decide.json()["status"] == "APPROVED"

    # Self-approval over the API is rejected.
    self_request = operator.post(
        "/api/v1/approvals",
        json={"gate": "CLIENT_OUTBOUND_COMMS", "title": "Another digest",
              "payload": {"to": "client@example.com"}},
    )
    assert self_request.status_code == 201
    self_decide = operator.post(
        f"/api/v1/approvals/{self_request.json()['id']}/decide",
        json={"decision": "APPROVED"},
    )
    assert self_decide.status_code == 403


def test_audit_endpoint_requires_internal_role(app, db, client, seed) -> None:
    from app.modules.crm import service as crm
    from tests.conftest import AuthClient

    c = crm.create_client(db, principal=_founder(seed), display_name="P Corp")
    make_user(db, email="cmember@example.com", password="PortalPass#1",
              tenant_id=seed.tenant.id, role=UserRole.CLIENT_MEMBER, client_id=c.id)
    db.commit()
    portal = AuthClient(app, "cmember@example.com", "PortalPass#1")
    assert portal.get("/api/v1/audit-events").status_code == 403


def _founder(seed) -> Principal:
    return principal_for(seed.admin, seed.tenant.id, role=UserRole.SUPER_ADMIN)
