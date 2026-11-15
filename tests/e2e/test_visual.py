"""Visual verification (docs/16): screenshot capture and design comparison.

Breakpoints (agreed for the E2E environment): desktop 1280x800 for console
and portal screens, mobile 390x844 for the login page. Screenshots are
full-page captures of the deterministically seeded state (frozen
timestamps); the audit screen is excluded because it renders live
timestamps (docs/16: dynamic content regions excluded explicitly).

Compare mode (default): full-page PNG vs tests/e2e/baselines/<name>.png,
pixel diff ratio must stay <= 0.2% (same browser + fonts + data). Baseline
update mode: AKNJA_E2E_UPDATE_BASELINES=1 regenerates baselines and passes.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.e2e.conftest import (
    E2E_CLIENT_EMAIL,
    E2E_CLIENT_PASSWORD,
    E2E_FOUNDER_EMAIL,
    E2E_FOUNDER_PASSWORD,
    current_seed_ids,
    login,
    reseed,
)

pytestmark = pytest.mark.e2e

BASELINES = Path(__file__).parent / "baselines"
DIFF_TOLERANCE = 0.002  # 0.2% of pixels may differ
UPDATE_BASELINES = os.environ.get("AKNJA_E2E_UPDATE_BASELINES") == "1"

DESKTOP_SCREENS = [
    "admin-dashboard",
    "admin-leads",
    "admin-catalog",
    "admin-providers",
    "admin-reports",
    "portal-project",
]


@pytest.fixture(scope="module", autouse=True)
def deterministic_state(server_url):
    """Restore the exact seeded state before capturing (functional E2E ran
    first and mutated the database; reseed gives byte-stable screenshots)."""
    reseed()
    yield


def _assert_matches_baseline(name: str, png: bytes) -> None:
    baseline = BASELINES / f"{name}.png"
    if UPDATE_BASELINES:
        BASELINES.mkdir(parents=True, exist_ok=True)
        baseline.write_bytes(png)
        return
    if not baseline.exists():
        pytest.fail(f"missing baseline {baseline} — run with AKNJA_E2E_UPDATE_BASELINES=1")

    from io import BytesIO

    from PIL import Image, ImageChops

    actual = Image.open(BytesIO(png)).convert("RGB")
    expected = Image.open(baseline).convert("RGB")
    assert actual.size == expected.size, (
        f"{name}: size changed {expected.size} -> {actual.size} — design regression?"
    )
    diff = ImageChops.difference(actual, expected)
    bbox = diff.getbbox()
    if bbox is None:
        return  # pixel-identical
    hist = diff.convert("L").histogram()
    changed = sum(hist[17:])  # pixels with meaningful channel delta (>16)
    ratio = changed / (actual.size[0] * actual.size[1])
    assert ratio <= DIFF_TOLERANCE, (
        f"{name}: visual diff {ratio:.4%} exceeds {DIFF_TOLERANCE:.2%} tolerance "
        f"(changed region {bbox}); if intentional, regenerate baselines with "
        "AKNJA_E2E_UPDATE_BASELINES=1"
    )


def _capture(page, url: str) -> bytes:
    page.goto(url)
    page.wait_for_load_state("networkidle")
    return page.screenshot(full_page=True)


def test_visual_login_desktop(page, server_url) -> None:
    _assert_matches_baseline("login-desktop", _capture(page, f"{server_url}/login"))


def test_visual_login_mobile(browser, server_url) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844})
    mobile = context.new_page()
    try:
        _assert_matches_baseline("login-mobile", _capture(mobile, f"{server_url}/login"))
    finally:
        context.close()


@pytest.mark.parametrize("screen", DESKTOP_SCREENS)
def test_visual_console_screens(page, server_url, screen) -> None:
    if screen == "portal-project":
        login(page, server_url, E2E_CLIENT_EMAIL, E2E_CLIENT_PASSWORD)
        url = f"{server_url}/portal/projects/{current_seed_ids()['project_id']}"
    else:
        login(page, server_url, E2E_FOUNDER_EMAIL, E2E_FOUNDER_PASSWORD)
        url = f"{server_url}/admin/{screen.removeprefix('admin-')}"
    _assert_matches_baseline(screen, _capture(page, url))
