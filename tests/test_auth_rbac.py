"""Phase 0/1 tests: app factory, health, auth, sessions, CSRF, RBAC,
tenant isolation (Phase 1 exit criterion)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.enums import UserRole
from app.modules.crm import service as crm
from app.modules.delivery import service as delivery
from app.modules.delivery.models import Project
from app.modules.identity.service import Principal
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, AuthClient, make_tenant, make_user


def founder_principal(seed) -> Principal:
    return Principal(
        user_id=seed.admin.id,
        email=seed.admin.email,
        tenant_id=seed.tenant.id,
        role=UserRole.SUPER_ADMIN,
        client_id=None,
        session_id=seed.admin.id,
        csrf_token="",
    )


# ------------------------------------------------------------------ health


def test_health_endpoints(client: TestClient) -> None:
    assert client.get("/health/live").json() == {"status": "alive"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["database"] == "ok"


def test_error_envelope_on_404(client: TestClient) -> None:
    resp = client.get("/api/v1/nonexistent")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert "request_id" in body["error"]


# -------------------------------------------------------------------- auth


def test_login_success_and_session(admin_client) -> None:
    me = admin_client.get("/api/v1/auth/session")
    assert me.status_code == 200
    assert me.json()["role"] == "SUPER_ADMIN"
    assert me.json()["email"] == ADMIN_EMAIL


def test_login_wrong_password(client, seed) -> None:
    resp = client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "WrongPass#9x"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_login_lockout_after_failures(client, seed) -> None:
    for _ in range(11):
        client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "badpass12"})
    resp = client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert resp.status_code == 401  # locked even with the right password


def test_authenticated_routes_require_login(client, seed) -> None:
    for url in ("/api/v1/leads", "/api/v1/clients", "/api/v1/projects"):
        assert client.get(url).status_code == 401, url


def test_logout_revokes_session(admin_client, client) -> None:
    assert admin_client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/session").status_code == 401


def test_mutation_requires_csrf_header(client, seed) -> None:
    login = client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 200
    resp = client.post("/api/v1/leads", json={"title": "no-csrf lead"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_csrf_mismatch_rejected(client, seed) -> None:
    client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    resp = client.post(
        "/api/v1/leads",
        json={"title": "forged lead"},
        headers={"x-csrf-token": "forged-token-value"},
    )
    assert resp.status_code == 403


# -------------------------------------------------------------------- RBAC


def test_read_only_auditor_cannot_write(app, db, client, seed) -> None:
    make_user(
        db,
        email="auditor@example.com",
        password="AuditorPass#1",
        tenant_id=seed.tenant.id,
        role=UserRole.READ_ONLY_AUDITOR,
    )
    db.commit()
    auditor = AuthClient(app, "auditor@example.com", "AuditorPass#1")
    assert auditor.get("/api/v1/leads").status_code == 200
    resp = auditor.post("/api/v1/leads", json={"title": "auditor attempt"})
    assert resp.status_code == 403


# -------------------------------------------------------- tenant isolation


def test_tenant_isolation_clients(app, db, client, seed) -> None:
    """Cross-tenant access must be impossible (Phase 1 exit criterion)."""
    other = make_tenant(db, "Other Agency", "other-agency")
    make_user(
        db,
        email="other-admin@example.com",
        password="OtherAdmin#1",
        tenant_id=other.id,
        role=UserRole.SUPER_ADMIN,
    )
    db.commit()
    other_client = AuthClient(app, "other-admin@example.com", "OtherAdmin#1")

    created = other_client.post("/api/v1/clients", json={"display_name": "Other Tenant Client"})
    assert created.status_code == 201
    other_client_id = uuid.UUID(created.json()["id"])

    mine = admin_client_list(app, client)
    assert all(c["id"] != str(other_client_id) for c in mine)

    # Direct access by UUID from the wrong tenant → 404 (no existence leak).
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        crm.get_client(db, seed.tenant.id, other_client_id)


def admin_client_list(app, client: TestClient) -> list[dict]:
    ac = AuthClient(app, ADMIN_EMAIL, ADMIN_PASSWORD)
    resp = ac.get("/api/v1/clients")
    assert resp.status_code == 200
    return resp.json()


def test_portal_user_scoped_to_own_client_only(app, db, client, seed) -> None:
    """Portal roles see only their own client's projects."""
    principal = founder_principal(seed)
    client_a = crm.create_client(db, principal=principal, display_name="Client A")
    client_b = crm.create_client(db, principal=principal, display_name="Client B")
    delivery.create_project(db, principal=principal, client_id=client_a.id, name="Project A")
    project_b = delivery.create_project(
        db, principal=principal, client_id=client_b.id, name="Project B"
    )
    db.commit()

    make_user(
        db,
        email="owner.a@example.com",
        password="PortalPass#1",
        tenant_id=seed.tenant.id,
        role=UserRole.CLIENT_OWNER,
        client_id=client_a.id,
    )
    db.commit()

    portal = AuthClient(app, "owner.a@example.com", "PortalPass#1")
    home = portal.get("/portal")
    assert home.status_code == 200
    assert "Project A" in home.text
    assert "Project B" not in home.text
    # Directly opening Client B's project → 404.
    assert portal.get(f"/portal/projects/{project_b.id}").status_code == 404


def test_audit_list_restricted_to_internal_roles(app, db, client, seed) -> None:
    principal = founder_principal(seed)
    client_a = crm.create_client(db, principal=principal, display_name="Portal Co")
    make_user(
        db,
        email="member@example.com",
        password="PortalPass#1",
        tenant_id=seed.tenant.id,
        role=UserRole.CLIENT_MEMBER,
        client_id=client_a.id,
    )
    db.commit()
    portal = AuthClient(app, "member@example.com", "PortalPass#1")
    resp = portal.get("/api/v1/audit-events")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_project_queries_are_tenant_filtered(db, seed) -> None:
    """Service-layer listing never returns other tenants' rows."""
    other = make_tenant(db, "Second Tenant", "second-tenant")
    principal = founder_principal(seed)
    mine = delivery.create_project(
        db, principal=principal, client_id=crm.create_client(db, principal=principal, display_name="C").id,
        name="Mine",
    )
    # A project row owned by the other tenant (inserted directly).
    other_project = Project(
        tenant_id=other.id,
        client_id=crm.create_client(db, principal=principal, display_name="X").id,
        name="Not Mine",
    )
    db.add(other_project)
    db.commit()
    listed = delivery.list_projects(db, seed.tenant.id)
    names = {p.name for p in listed}
    assert "Mine" in names
    assert "Not Mine" not in names
    assert mine.tenant_id == seed.tenant.id
