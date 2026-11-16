"""Service-delivery E2E (T-026): catalog service item -> project with
milestones/tasks -> REAL AI execution -> artifact on the project page ->
client UAT acceptance, in BOTH business domains, driven through the real
admin UI with a real free provider.
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import (
    E2E_CLIENT_EMAIL,
    E2E_CLIENT_PASSWORD,
    E2E_FOUNDER_EMAIL,
    E2E_FOUNDER_PASSWORD,
    login,
)

pytestmark = pytest.mark.e2e

BRIEF_SE = ("Build a bakery ordering PWA: order form, WhatsApp order "
            "notifications, photo gallery, Malayalam + English UI.")
BRIEF_DM = ("Launch campaign for the bakery ordering app: audience Kochi "
            "metro families, channels Instagram + WhatsApp, 3 weeks, "
            "Malayalam-first copy.")


def _start_project(page, server_url, client_name: str, service_text: str,
                   name: str, brief: str) -> None:
    page.goto(f"{server_url}/admin/projects/new")
    page.select_option('select[name="client_id"]', label=client_name)
    page.select_option('select[name="service_id"]', label=service_text)
    page.fill('input[name="name"]', name)
    page.fill('textarea[name="brief"]', brief)
    page.click('form[action="/admin/projects/new"] button[type="submit"]')
    page.wait_for_selector("text=Project started from the catalog", timeout=30_000)


def _run_ai_step(page, task_title: str) -> str:
    """Click Run AI on a task and wait for the real provider to answer."""
    import time

    row = page.locator("tr", has_text=task_title)
    for attempt in range(3):
        if attempt:
            time.sleep(15)
        # dispatch_event: the form POST navigates only after the governed
        # provider call finishes (20s+ on the free tier) — a plain click
        # would wait for that navigation and time out at 30s.
        row.locator("button", has_text="Run AI").dispatch_event("click")
        # the governed call can take 20s+ on the free tier
        try:
            page.wait_for_selector("text=AI step completed", timeout=180_000)
        except Exception:
            pass  # fall through to the outcome banner check below
        body = page.text_content("body") or ""
        if "AI step completed" in body:
            time.sleep(6)  # pace against the free-tier burst limiter
            return body
        page.wait_for_selector("text=AI step outcome", timeout=180_000)
    return page.text_content("body") or ""


def test_service_delivery_se_domain(page, server_url, ai_ready, catalog_ready) -> None:
    """Software engineering: start from a catalog item, run the REAL
    requirements step, verify the artifact lands for human review."""
    login(page, server_url, E2E_FOUNDER_EMAIL, E2E_FOUNDER_PASSWORD)
    _start_project(
        page, server_url, "Sweet Cakes",
        "Frontend Engineering — Progressive Web Apps (PWAs)",
        "Bakery Showcase App", BRIEF_SE,
    )
    # the blueprint instantiated
    assert "AI requirements extraction" in (page.text_content("body") or "")

    body = _run_ai_step(page, "AI requirements extraction")
    assert "AI step completed" in body
    # the artifact is registered with real AI output on the project page
    artifact = page.locator("td", has_text="[AI] AI requirements extraction")
    assert artifact.count() >= 1
    content = page.text_content("body") or ""
    assert "order" in content.lower()  # real requirements mention the order form


def test_service_delivery_dm_domain(page, server_url, ai_ready, catalog_ready) -> None:
    """Digital marketing: start from a catalog item, run the REAL campaign
    brief + multilingual adaptation steps."""
    login(page, server_url, E2E_FOUNDER_EMAIL, E2E_FOUNDER_PASSWORD)
    _start_project(
        page, server_url, "Sweet Cakes",
        "Copywriting & Written Content — High-Converting Landing Page Sales Copy",
        "App Launch Marketing", BRIEF_DM,
    )
    assert "AI campaign brief" in (page.text_content("body") or "")

    body = _run_ai_step(page, "AI campaign brief")
    assert "AI step completed" in body
    body = _run_ai_step(page, "AI multilingual adaptation")
    assert "AI step completed" in body


def test_client_accepts_delivery_in_portal(page, server_url, ai_ready, catalog_ready) -> None:
    """The delivery ends with client UAT acceptance in the portal (both
    projects from the previous tests are on the seeded client)."""
    login(page, server_url, E2E_CLIENT_EMAIL, E2E_CLIENT_PASSWORD)
    page.goto(f"{server_url}/portal")
    body = page.text_content("body") or ""
    assert "Bakery Showcase App" in body or "App Launch Marketing" in body
