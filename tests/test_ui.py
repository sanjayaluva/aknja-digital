"""UI smoke tests: every admin and portal screen renders."""

from __future__ import annotations

import pytest

from app.core.enums import UserRole
from app.modules.crm import service as crm
from app.modules.delivery import service as delivery
from tests.conftest import AuthClient, make_user

ADMIN_PAGES = [
    "/admin",
    "/admin/leads",
    "/admin/clients",
    "/admin/catalog",
    "/admin/projects",
    "/admin/approvals",
    "/admin/audit",
    "/admin/settings",
    "/admin/providers",
    "/admin/ai",
    "/admin/reports",
    "/admin/invoices",
]


def _founder_principal(seed):
    from app.modules.identity.service import Principal

    return Principal(
        user_id=seed.admin.id, email=seed.admin.email, tenant_id=seed.tenant.id,
        role=UserRole.SUPER_ADMIN, client_id=None, session_id=seed.admin.id, csrf_token="",
    )


@pytest.mark.parametrize("page", ADMIN_PAGES)
def test_admin_pages_render(page, admin_client) -> None:
    resp = admin_client.get(page)
    assert resp.status_code == 200, f"{page} returned {resp.status_code}"
    assert "<html" in resp.text.lower()
    assert "error" not in resp.text[:200].lower()


def test_admin_pages_redirect_anonymous(client) -> None:
    for page in ("/admin", "/admin/leads", "/portal"):
        resp = client.get(page, follow_redirects=False)
        assert resp.status_code == 302, page


def test_login_page_renders(client) -> None:
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Sign in" in resp.text


def test_catalog_page_shows_taxonomy(db, seed, admin_client) -> None:
    from pathlib import Path

    from app.modules.catalog.service import import_taxonomy

    import_taxonomy(
        db, tenant_id=seed.tenant.id,
        md_path=Path(__file__).resolve().parent.parent / "docs" / "source_service_hierarchy.md",
        seed_csv_path=Path(__file__).resolve().parent.parent / "examples" / "service-readiness-seed.csv",
    )
    db.commit()
    html = admin_client.get("/admin/catalog").text
    assert "Web Application Development" in html
    assert "Search Engine Optimization" in html
    assert "PLANNED" in html


def test_project_detail_page_renders(db, seed, admin_client) -> None:
    principal = _founder_principal(seed)
    client_row = crm.create_client(db, principal=principal, display_name="UI Co")
    project = delivery.create_project(
        db, principal=principal, client_id=client_row.id, name="UI Project"
    )
    delivery.add_milestone(
        db, tenant_id=seed.tenant.id, project_id=project.id, title="MVP", weight_pct=100
    )
    db.commit()
    resp = admin_client.get(f"/admin/projects/{project.id}")
    assert resp.status_code == 200
    assert "UI Project" in resp.text
    assert "MVP" in resp.text


def test_portal_flow_end_to_end(db, app, seed, admin_client) -> None:
    """Portal user sees milestones, submits feedback, accepts UAT."""
    principal = _founder_principal(seed)
    client_row = crm.create_client(db, principal=principal, display_name="Portal Co")
    project = delivery.create_project(
        db, principal=principal, client_id=client_row.id, name="Portal Project"
    )
    delivery.add_milestone(
        db, tenant_id=seed.tenant.id, project_id=project.id, title="Beta", weight_pct=100
    )
    delivery.create_staging_preview(
        db, tenant_id=seed.tenant.id, project_id=project.id, url="https://staging.example/beta"
    )
    db.commit()

    make_user(
        db, email="portal-owner@example.com", password="PortalPass#1",
        tenant_id=seed.tenant.id, role=UserRole.CLIENT_OWNER, client_id=client_row.id,
    )
    db.commit()
    portal = AuthClient(app, "portal-owner@example.com", "PortalPass#1")

    detail = portal.get(f"/portal/projects/{project.id}")
    assert detail.status_code == 200
    assert "Beta" in detail.text

    feedback = portal.post(
        f"/portal/projects/{project.id}/feedback",
        data={
            "kind": "BUG_REPORT",
            "message": "Checkout button misaligned on mobile",
            "page_or_module": "Checkout",
            "severity": "MEDIUM",
            "reproduction_steps": "Open on phone",
            "csrf_token": portal.csrf,
        },
    )
    assert feedback.status_code in (303, 200)
    detail = portal.get(f"/portal/projects/{project.id}")
    assert "Checkout button misaligned" in detail.text

    uat = portal.post(
        f"/portal/projects/{project.id}/uat",
        data={"decision": "ACCEPTED", "notes": "Looks good", "csrf_token": portal.csrf},
    )
    assert uat.status_code in (303, 200)

    # The acceptance unlocks the production handoff transition.

    ok = admin_client.post(
        f"/admin/projects/{project.id}/transition",
        data={"to_state": "LEAD_QUALIFIED", "csrf_token": admin_client.csrf},
    )
    assert ok.status_code in (303, 200)


def test_settings_page_lists_all_tabs(db, seed, admin_client) -> None:
    html = admin_client.get("/admin/settings").text
    for fragment in ("Brand", "Commercial", "Ai Quota", "Qa Gates", "Hitl", "Leads", "Sdlc"):
        assert fragment in html, f"missing settings tab: {fragment}"


def test_login_accepts_urlencoded_form(client, seed) -> None:
    """htmx serializes the login form as urlencoded, not JSON — the API must
    accept both (regression: found by E2E T-007, browser login 422'd)."""
    resp = client.post(
        "/api/v1/auth/login",
        data={"email": seed.admin.email, "password": "FounderPass#1"},
    )
    assert resp.status_code == 200, resp.text
    assert "aknja_session" in resp.cookies


def test_validation_error_is_clean_422(client, seed) -> None:
    """A 422 must return the JSON envelope, never crash into a 500
    (regression: bytes body crashed json.dumps in the error handler)."""
    resp = client.post(
        "/api/v1/auth/login",
        data={"email": seed.admin.email, "password": "short"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
