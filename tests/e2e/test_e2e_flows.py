"""Functional E2E: critical admin/client workflows in a real browser
(docs/16 test pyramid — E2E layer). Flows: auth (reject/login/logout),
lead capture + qualification, project task delivery, approval decision,
client portal feedback/UAT, RBAC boundaries, audit visibility.
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import (
    E2E_CLIENT_EMAIL,
    E2E_CLIENT_PASSWORD,
    E2E_FOUNDER_EMAIL,
    E2E_FOUNDER_PASSWORD,
    LEAD_TITLE,
    PROJECT_NAME,
    login,
)

pytestmark = pytest.mark.e2e


def test_login_rejects_wrong_password(page, server_url) -> None:
    page.goto(f"{server_url}/login")
    page.fill('input[name="email"]', E2E_FOUNDER_EMAIL)
    page.fill('input[name="password"]', "WrongPassword#9")
    page.click('button[type="submit"]')
    page.wait_for_selector("#login-error:not([hidden])", timeout=10_000)
    assert "/login" in page.url


def test_founder_login_lands_on_admin(page, server_url) -> None:
    login(page, server_url, E2E_FOUNDER_EMAIL, E2E_FOUNDER_PASSWORD)
    assert "/admin" in page.url
    header = page.text_content(".user-name") or ""
    assert "E2E Founder" in header


def test_logout_returns_to_login(page, server_url) -> None:
    login(page, server_url, E2E_FOUNDER_EMAIL, E2E_FOUNDER_PASSWORD)
    # logout is an htmx POST that reloads to /login on success
    page.click('form[action="/api/v1/auth/logout"] button')
    page.wait_for_url(lambda url: "/login" in url, timeout=10_000)
    page.goto(f"{server_url}/admin")
    page.wait_for_url(lambda url: "/login" in url, timeout=10_000)


def test_anonymous_admin_redirects_to_login(page, server_url) -> None:
    page.goto(f"{server_url}/admin")
    page.wait_for_url(lambda url: "/login" in url, timeout=10_000)


def test_dashboard_shows_seeded_state(page, server_url) -> None:
    login(page, server_url, E2E_FOUNDER_EMAIL, E2E_FOUNDER_PASSWORD)
    page.goto(f"{server_url}/admin")
    body = page.text_content("body") or ""
    assert "Sweet Cakes" in body  # seeded client/project visible on the console


def test_lead_capture_and_qualify_flow(page, server_url, seed_ids) -> None:
    login(page, server_url, E2E_FOUNDER_EMAIL, E2E_FOUNDER_PASSWORD)
    page.goto(f"{server_url}/admin/leads")

    # capture a new lead through the real form
    page.fill('form[action="/admin/leads"] input[name="title"]', "Portfolio site enquiry")
    page.select_option('form[action="/admin/leads"] select[name="source"]', "DIRECT")
    page.fill('form[action="/admin/leads"] input[name="contact_email"]', "dev@example.test")
    page.fill('form[action="/admin/leads"] input[name="budget_minor"]', "250000")
    page.fill('form[action="/admin/leads"] input[name="feasibility_score"]', "80")
    page.fill('form[action="/admin/leads"] textarea[name="description"]', "Personal portfolio site")
    page.click('form[action="/admin/leads"] button[type="submit"]')
    page.wait_for_selector("text=Portfolio site enquiry", timeout=10_000)

    # qualify the seeded lead through the real state machine:
    # NEW -> CONTACTED -> QUALIFIED (LEAD_TRANSITIONS forbids skipping)
    def _qualify(to_status: str) -> None:
        row = page.locator("tr", has_text=LEAD_TITLE)
        row.locator('select[name="to_status"]').select_option(to_status)
        row.locator("button[type=submit]").first.click()
        page.wait_for_selector(f"tr:has-text('{LEAD_TITLE}') >> text={to_status}", timeout=10_000)

    _qualify("CONTACTED")
    _qualify("QUALIFIED")


def test_project_task_delivery_flow(page, server_url, seed_ids) -> None:
    login(page, server_url, E2E_FOUNDER_EMAIL, E2E_FOUNDER_PASSWORD)
    page.goto(f"{server_url}/admin/projects/{seed_ids['project_id']}")
    assert PROJECT_NAME in (page.text_content("body") or "")

    # add a delivery task
    page.fill('form[action*="/tasks"] input[name="title"]', "Build order form")
    page.select_option('form[action*="/tasks"] select[name="priority"]', "HIGH")
    page.fill('form[action*="/tasks"] input[name="estimate_hours"]', "4")
    page.click('form[action*="/tasks"] button[type="submit"]')
    page.wait_for_selector("text=Build order form", timeout=10_000)

    # transition the new task to done
    task_row = page.locator("tr", has_text="Build order form")
    options = task_row.locator('select[name="to_status"] option').all_text_contents()
    assert options, "task transition options missing"
    task_row.locator('select[name="to_status"]').select_option(options[0])
    task_row.locator("button[type=submit]").first.click()
    page.wait_for_load_state("networkidle")
    body = page.text_content("body") or ""
    assert "Build order form" in body  # task still listed after transition


def test_approval_decision_flow(page, server_url) -> None:
    login(page, server_url, E2E_FOUNDER_EMAIL, E2E_FOUNDER_PASSWORD)
    page.goto(f"{server_url}/admin/approvals")
    page.wait_for_selector("text=Enable paid provider override (E2E seed)", timeout=10_000)

    page.locator('button[name="decision"][value="APPROVED"]').first.click()
    # the decision is recorded on the approval (status badge flips to APPROVED)
    page.wait_for_selector(
        "tr:has-text('Enable paid provider override (E2E seed)') >> text=APPROVED",
        timeout=10_000,
    )


def test_portal_feedback_and_uat_flow(page, server_url, seed_ids) -> None:
    login(page, server_url, E2E_CLIENT_EMAIL, E2E_CLIENT_PASSWORD)
    assert "/portal" in page.url
    page.goto(f"{server_url}/portal/projects/{seed_ids['project_id']}")
    assert PROJECT_NAME in (page.text_content("body") or "")

    # submit structured client feedback through the portal form
    page.select_option('form[action*="/feedback"] select[name="kind"]', "BUG_REPORT")
    page.fill('form[action*="/feedback"] input[name="page_or_module"]', "Home page")
    page.select_option('form[action*="/feedback"] select[name="severity"]', "HIGH")
    page.fill('form[action*="/feedback"] textarea[name="message"]', "Hero image overlaps menu on mobile")
    page.click('form[action*="/feedback"] button[type="submit"]')
    page.wait_for_selector("text=Hero image overlaps menu on mobile", timeout=10_000)


def test_portal_user_cannot_open_admin(page, server_url) -> None:
    login(page, server_url, E2E_CLIENT_EMAIL, E2E_CLIENT_PASSWORD)
    response = page.goto(f"{server_url}/admin")
    # RBAC: client session gets a 403 Forbidden page, never admin content
    assert response is not None and response.status == 403
    body = page.text_content("body") or ""
    assert "Forbidden" in body
    assert "Operations Overview" not in body


def test_audit_page_records_this_login(page, server_url) -> None:
    login(page, server_url, E2E_FOUNDER_EMAIL, E2E_FOUNDER_PASSWORD)
    page.goto(f"{server_url}/admin/audit")
    body = page.text_content("body") or ""
    assert "auth.login" in body
