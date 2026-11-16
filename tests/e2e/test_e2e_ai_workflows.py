"""AI-workflow E2E (T-025): real input -> governed inference -> real output for
every task profile, in both business domains, through the real app with REAL
free-tier providers (sandbox-reachable: openrouter / github_models /
cloudflare; keys come from the local .env).

Digital-marketing domain: translation (client portal page), classification,
summarization (gateway llm.generate tool).
Software-engineering domain: requirements, code_review, qa_review,
proposal_draft (gateway llm.generate tool).

These assert FUNCTIONING (a real, non-empty, sane answer arrives through the
governed path); quality floors are measured by the benchmark suite, not here.
"""

from __future__ import annotations

import json

import pytest

from tests.e2e.conftest import (
    E2E_CLIENT_EMAIL,
    E2E_CLIENT_PASSWORD,
    E2E_FOUNDER_EMAIL,
    E2E_FOUNDER_PASSWORD,
    login,
)

pytestmark = pytest.mark.e2e

# Free-tier pools burst-throttle (openrouter :free answers 429s when calls
# arrive back-to-back — live 2026-11-15); pace the workflow and allow a
# governed-retry pause instead of failing the suite on a transient 429.
_CALL_PACE_S = 6.0
_RETRY_PAUSE_S = 20.0


def _csrf_from_page(page) -> str:
    """The founder console embeds the session CSRF token in the logout form."""
    hx = page.get_attribute("form[action='/api/v1/auth/logout']", "hx-headers")
    assert hx, "csrf-bearing logout form not found"
    return json.loads(hx)["x-csrf-token"]


def _run_tool(page, server_url: str, task: str, prompt: str) -> dict:
    """One governed llm.generate execution through the real API surface.

    Paces calls against the free tier's burst limiter and retries once after
    a pause when every pool member answered 429 (a governed PENDING_MANUAL,
    not an app defect — the retry proves the workflow completes in practice).
    """
    import time

    last: dict = {}
    for attempt in range(4):
        if attempt:
            time.sleep(_RETRY_PAUSE_S)
        resp = page.request.post(
            f"{server_url}/api/v1/tools/execute",
            headers={"x-csrf-token": _csrf_from_page(page)},
            timeout=180_000,  # free-tier completions run 20s+ (live 2026-11-15)
            data={
                "tool_name": "llm.generate",
                "arguments": {"task": task, "prompt": prompt,
                              "data_classification": "INTERNAL"},
                "idempotency_key": f"e2e-ai-{task}-{attempt}-{id(prompt):x}",
            },
        )
        assert resp.status == 200, f"{task}: HTTP {resp.status} {resp.text()[:300]}"
        last = resp.json()
        result = last.get("result") or {}
        if last.get("status") == "SUCCEEDED" and result.get("status") == "SUCCEEDED":
            time.sleep(_CALL_PACE_S)
            return last
    return last


# --- digital marketing domain ----------------------------------------------------


def test_dm_translation_via_client_portal(page, server_url, ai_ready) -> None:
    """The client-facing translation service: real text in, real Malayalam out."""
    login(page, server_url, E2E_CLIENT_EMAIL, E2E_CLIENT_PASSWORD)
    page.goto(f"{server_url}/portal/translate")
    page.select_option('select[name="source"]', "en")
    page.select_option('select[name="target"]', "ml")
    page.fill('textarea[name="text"]',
              "Aknja Digital will launch the new client portal next Friday.")
    # scope to the translate form — the sidebar logout form also carries a
    # submit button and sits earlier in the DOM
    page.click('form[action="/portal/translate"] button[type="submit"]')
    page.wait_for_selector(".translation-output", timeout=120_000)
    output = (page.text_content(".translation-output") or "").strip()
    assert len(output.split()) >= 3, f"translation too short: {output!r}"
    # engine attribution is shown to the client
    engine = page.text_content("body") or ""
    assert "Engine:" in engine


def test_dm_classification_and_summarization(page, server_url, ai_ready) -> None:
    login(page, server_url, E2E_FOUNDER_EMAIL, E2E_FOUNDER_PASSWORD)
    page.goto(f"{server_url}/admin")

    out = _run_tool(page, server_url, "classification",
                    'Classify the support ticket below into exactly one category: '
                    'BILLING, TECHNICAL, SCHEDULE, OTHER. Output strict JSON only: '
                    '{"label": "CATEGORY"}.\n\nTicket: My monthly invoice shows a '
                    'double charge for the hosting plan. Please correct it.')
    assert out["status"] == "SUCCEEDED", out
    assert out["result"]["status"] == "SUCCEEDED", out["result"]["reason"]
    label = json.loads(out["result"]["text"])["label"]
    assert label in {"BILLING", "TECHNICAL", "SCHEDULE", "OTHER"}

    out = _run_tool(page, server_url, "summarization",
                    "Summarize the project update below in at most 40 words. Keep "
                    "the key facts and dates. Output only the summary.\n\nUpdate: "
                    "The client portal design phase completed on 12 November. The "
                    "payment gateway integration is now in testing and is expected "
                    "to finish by 20 November, two days ahead of the schedule.")
    assert out["status"] == "SUCCEEDED" and out["result"]["status"] == "SUCCEEDED"
    summary = out["result"]["text"]
    assert 3 <= len(summary.split()) <= 60, summary


# --- software engineering domain -------------------------------------------------


def test_se_requirements_and_code_review(page, server_url, ai_ready) -> None:
    login(page, server_url, E2E_FOUNDER_EMAIL, E2E_FOUNDER_PASSWORD)
    page.goto(f"{server_url}/admin")

    out = _run_tool(page, server_url, "requirements",
                    "Extract the functional requirements from this client brief as "
                    'a JSON array of {"id", "requirement", "priority"}: "We need a '
                    'bakery website with an online order form, WhatsApp order '
                    'notifications, and a photo gallery. The order form is urgent; '
                    'the gallery can wait."')
    assert out["status"] == "SUCCEEDED" and out["result"]["status"] == "SUCCEEDED"
    text = out["result"]["text"]
    assert len(text) > 40, text

    out = _run_tool(page, server_url, "code_review",
                    'Review this Python function and output JSON '
                    '{"findings": [{"severity", "comment"}]}:\n'
                    "def divide(a, b):\n    return a / b\n")
    assert out["status"] == "SUCCEEDED" and out["result"]["status"] == "SUCCEEDED"
    text = out["result"]["text"]
    assert len(text) > 20 and ("divide" in text.lower() or "finding" in text.lower())


def test_se_qa_review_and_proposal_draft(page, server_url, ai_ready) -> None:
    login(page, server_url, E2E_FOUNDER_EMAIL, E2E_FOUNDER_PASSWORD)
    page.goto(f"{server_url}/admin")

    out = _run_tool(page, server_url, "qa_review",
                    'QA-review this delivery note and output JSON {"verdict": '
                    '"PASS|FAIL", "issues": []}: "Delivered: 5-page website. '
                    'Tested: home, about, menu, contact pages in Chrome. Not '
                    'tested: the order form submit flow on mobile."')
    assert out["status"] == "SUCCEEDED" and out["result"]["status"] == "SUCCEEDED"
    assert len(out["result"]["text"]) > 20

    out = _run_tool(page, server_url, "proposal_draft",
                    "Draft a short proposal (3 sections: Scope, Timeline, "
                    "Commercial) for a Kochi bakery that needs a five-page "
                    "website with an online order form. Budget around Rs 50,000.")
    assert out["status"] == "SUCCEEDED" and out["result"]["status"] == "SUCCEEDED"
    assert len(out["result"]["text"].split()) >= 30
