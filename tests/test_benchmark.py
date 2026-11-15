"""LLM quality benchmark runner (v5.3.2 §5C/§6, round T-008).

Pins: scenario bank integrity (7 tasks × 4 languages), deterministic
evaluators (JSON validity, label match, entity/script preservation, key
facts, length bounds, sections), the runner against mocked providers
(scorecard + durable record + founder alert on failure), and the §6
inference gate (failed providers skipped for failed tasks; passed, stale
and unbenchmarked providers unaffected).
"""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.security import utcnow
from app.modules.ai.benchmark import (
    BENCHMARK_LANGUAGES,
    BENCHMARK_VERSION,
    QUALITY_FLOORS,
    SCENARIOS,
    _evaluate,
    _extract_json,
    _script_ratio,
    benchmark_gate,
    run_benchmark,
)
from app.modules.ai.inference import TASK_PROFILES, llm_complete
from app.modules.ops.models import NotificationOutbox
from app.modules.resources.candidates import register_candidate_providers
from app.modules.resources.models import ProviderQualityBenchmark
from tests.test_ai_inference import _settings, _verify_provider

PROVIDER = "groq"  # openai-compatible adapter shape for the mock transport


# --- bank integrity -----------------------------------------------------------


def test_bank_covers_every_task_in_every_language() -> None:
    assert len(SCENARIOS) == 36
    for task in TASK_PROFILES:
        for lang in BENCHMARK_LANGUAGES:
            scenarios = [s for s in SCENARIOS if s.task == task and s.language == lang]
            expected = 2 if task in ("classification", "translation") else 1
            assert len(scenarios) == expected, f"{task}/{lang}"
    assert QUALITY_FLOORS.keys() == TASK_PROFILES.keys()


def test_bank_prompts_unique_and_self_contained() -> None:
    prompts = [s.prompt for s in SCENARIOS]
    assert len(set(prompts)) == len(prompts)
    for s in SCENARIOS:
        assert len(s.prompt) > 40, s.id
        # every instruction carries its output contract (JSON or section words)
        if s.task in ("classification", "requirements", "code_review", "qa_review"):
            assert "JSON" in s.prompt or "json" in s.prompt, s.id


# --- evaluator units ----------------------------------------------------------


def test_extract_json_handles_fences_and_prose() -> None:
    assert _extract_json('{"label": "BILLING"}') == {"label": "BILLING"}
    assert _extract_json('```json\n{"label": "BILLING"}\n```') == {"label": "BILLING"}
    assert _extract_json('Sure! Here it is: {"label": "BILLING"} hope that helps') == {
        "label": "BILLING"
    }
    assert _extract_json("[1, 2]") == [1, 2]
    assert _extract_json("no json here") is None
    assert _extract_json("{broken") is None


def test_script_ratio_distinguishes_languages() -> None:
    assert _script_ratio("ഇത് ഒരു വാക്യം", "ml") == 1.0
    assert _script_ratio("यह एक वाक्य है", "hi") == 1.0
    assert _script_ratio("இது ஒரு வாக்கியம்", "ta") == 1.0
    assert _script_ratio("plain english text", "en") == 1.0
    assert _script_ratio("plain english text", "ml") == 0.0
    # mixed brand + target script still passes the 0.5 floor
    assert _script_ratio("Aknja Digital അടുത്ത വെള്ളിയാഴ്ച പോർട്ടൽ അവതരിപ്പിക്കും", "ml") > 0.5


def test_classification_evaluator() -> None:
    expect = {"json": True, "label": "BILLING"}
    assert _evaluate("classification", '{"label": "BILLING"}', expect) == []
    assert _evaluate("classification", "the ticket is about billing", expect) == ["invalid JSON"]
    checks = _evaluate("classification", '{"label": "TECHNICAL"}', expect)
    assert checks and "label mismatch" in checks[0]


def test_translation_evaluator() -> None:
    expect = {"entities": ["Aknja Digital"], "script": "ml", "min_words": 4}
    good = "Aknja Digital അടുത്ത വെള്ളിയാഴ്ച പുതിയ ക്ലയന്റ് പോർട്ടൽ അവതരിപ്പിക്കും."
    assert _evaluate("translation", good, expect) == []
    lost = _evaluate("translation", "അക്നജ ഡിജിറ്റൽ അടുത്ത വെള്ളിയാഴ്ച പോർട്ടൽ അവതരിപ്പിക്കും.", expect)
    assert any("entity lost" in c for c in lost)
    wrong = _evaluate("translation", "Aknja Digital will launch the portal next Friday.", expect)
    assert any("wrong script" in c for c in wrong)


def test_summarization_evaluator() -> None:
    expect = {"must_include": ["payment gateway", "March 10"], "min_words": 8, "max_words": 60,
              "source": "design done. gateway pending. launch March 10. writer available."}
    good = ("Portal design is complete, payment gateway testing remains, "
            "and the launch is set for March 10.")
    assert _evaluate("summarization", good, expect) == []
    assert any("key fact lost" in c for c in _evaluate(
        "summarization", "Design complete, testing remains, launch scheduled.", expect))
    too_long = " ".join(["word"] * 80)
    assert any("too long" in c for c in _evaluate("summarization", too_long, expect))
    assert any("verbatim" in c for c in _evaluate("summarization", expect["source"], expect))


def test_requirements_evaluator() -> None:
    expect = {"json": True, "min_items": 3, "must_include": ["order", "gallery"]}
    good = ('[{"id": "R1", "text": "Online order form"}, {"id": "R2", "text": "WhatsApp button"},'
            ' {"id": "R3", "text": "Cake photo gallery"}]')
    assert _evaluate("requirements", good, expect) == []
    assert _evaluate("requirements", "needs a form and a gallery", expect) == ["invalid JSON array"]
    short = '[{"id": "R1", "text": "Order form"}, {"id": "R2", "text": "Gallery"}]'
    assert any("fewer than 3" in c for c in _evaluate("requirements", short, expect))


def test_code_review_and_qa_evaluators() -> None:
    cr_expect = {"json": True, "min_findings": 1, "must_include": ["user.profile"]}
    good_cr = ('{"findings": [{"severity": "high", "comment": "user.profile may be null; '
               'guard before reading user.profile.name"}]}')
    assert _evaluate("code_review", good_cr, cr_expect) == []
    no_findings = '{"findings": []}'
    checks = _evaluate("code_review", no_findings, cr_expect)
    assert "no findings reported" in checks
    assert "defect not identified: user.profile" in checks

    qa_expect = {"json": True, "passed": False, "min_issues": 1, "must_include": ["404"]}
    good_qa = ('{"passed": false, "issues": [{"severity": "high", '
               '"description": "Download invoice link returns 404 on Chrome"}]}')
    assert _evaluate("qa_review", good_qa, qa_expect) == []
    wrong_verdict = '{"passed": true, "issues": [{"severity": "high", "description": "404 link"}]}'
    checks = _evaluate("qa_review", wrong_verdict, qa_expect)
    assert any("verdict mismatch" in c for c in checks)


def test_proposal_evaluator_sections_and_length() -> None:
    expect = {"sections": ["Objective", "Scope", "Timeline", "Pricing"],
              "min_words": 50, "max_words": 500}
    good = ("Objective: launch a modern bakery website that showcases products and "
            "accepts online orders. Scope: five pages, order form, gallery. "
            "Timeline: two weeks from kickoff to launch with testing included in the plan. "
            "Pricing: a fixed package of fifteen thousand rupees covering design, "
            "development, SEO setup and one month of support after launch, including "
            "two revision rounds for the client and a handover session.")
    assert _evaluate("proposal_draft", good, expect) == []
    missing = _evaluate("proposal_draft", "Objective: site. Scope: pages. Timeline: fast.", expect)
    assert any("missing section: Pricing" in c for c in missing)
    assert any("too short" in c for c in missing)


# --- canned good answers for the mock provider --------------------------------

_CLASSIFICATION = ['{"label": "BILLING"}', '{"label": "TECHNICAL"}']
_REQUIREMENTS = {
    "en": '[{"id":"R1","text":"Online order form"},{"id":"R2","text":"WhatsApp button on every page"},{"id":"R3","text":"Tamil language support"},{"id":"R4","text":"Cake photo gallery"}]',
    "ml": '[{"id":"R1","text":"ഓൺലൈൻ ഓർഡർ ഫോം"},{"id":"R2","text":"എല്ലാ പേജിലും വാട്ട്‌സ്ആപ്പ് ബട്ടൺ"},{"id":"R3","text":"തമിഴ് ഭാഷാ പിന്തുണ"},{"id":"R4","text":"കേക്ക് ഫോട്ടോ ഗാലറി"}]',
    "hi": '[{"id":"R1","text":"ऑनलाइन ऑर्डर फॉर्म"},{"id":"R2","text":"हर पेज पर WhatsApp बटन"},{"id":"R3","text":"तमिल भाषा समर्थन"},{"id":"R4","text":"केक फोटो गैलरी"}]',
    "ta": '[{"id":"R1","text":"ஆன்லைன் ஆர்டர் படிவம்"},{"id":"R2","text":"ஒவ்வொரு பக்கத்திலும் WhatsApp பட்டன்"},{"id":"R3","text":"தமிழ் மொழி ஆதரவு"},{"id":"R4","text":"கேக் புகைப்பட கேலரி"}]',
}
_TRANSLATION = {
    "en": ["Aknja Digital will launch the new client portal next Friday.",
           "Please confirm the payment gateway integration on WhatsApp before Monday."],
    "ml": ["Aknja Digital അടുത്ത വെള്ളിയാഴ്ച പുതിയ ക്ലയന്റ് പോർട്ടൽ അവതരിപ്പിക്കും.",
           "തിങ്കളാഴ്ചയ്ക്ക് മുമ്പ് WhatsApp-ൽ പേയ്മെന്റ് ഗേറ്റ്വേ ഇന്റഗ്രേഷൻ ഉറപ്പാക്കുക."],
    "hi": ["Aknja Digital अगले शुक्रवार नया क्लाइंट पोर्टल लॉन्च करेगा।",
           "कृपया सोमवार से पहले WhatsApp पर पेमेंट गेटवे इंटीग्रेशन की पुष्टि करें।"],
    "ta": ["Aknja Digital அடுத்த வெள்ளிக்கிழமை புதிய கிளையன்ட் போர்டலை தொடங்கும்.",
           "திங்கள்கிழமைக்கு முன் WhatsApp-இல் பேமெண்ட் கேட்வே ஒருங்கிணைப்பை உறுதிப்படுத்தவும்."],
}
_SUMMARY = {
    "en": "Portal design is complete, payment gateway testing remains, and launch is set for March 10.",
    "ml": "ക്ലയന്റ് പോർട്ടൽ ഡിസൈൻ പൂർത്തിയായി; പേയ്മെന്റ് ഗേറ്റ്വേ ടെസ്റ്റിംഗ് ബാക്കി; ലോഞ്ച് മാർച്ച് 10-ന്.",
    "hi": "पोर्टल डिज़ाइन पूरा हुआ, पेमेंट गेटवे टेस्टिंग बाकी है, लॉन्च 10 मार्च को होगा।",
    "ta": "போர்டல் வடிவமைப்பு முடிந்தது, பேமெண்ட் கேட்வே சோதனை மீதமுள்ளது, லாஞ்ச் மார்ச் 10.",
}
_CODE_REVIEW = ('{"findings": [{"severity": "high", "comment": "user.profile may be null; '
                'guard before reading user.profile.name"}]}')
_QA_REVIEW = ('{"passed": false, "issues": [{"severity": "high", '
              '"description": "Download invoice link returns 404 on Chrome"}]}')
_PROPOSAL = {
    "en": ("Objective: Launch a modern bakery website that showcases products and accepts "
           "online orders. Scope: Five pages — home, menu, gallery, about and contact; an "
           "online order form; a WhatsApp button on every page; English and Tamil content; "
           "a mobile-first responsive design. Timeline: Design in week one; development and "
           "content loading in week two; testing and launch within fourteen working days. "
           "Pricing: A fixed package of ₹15,000 covering design, development, basic SEO "
           "setup and one month of post-launch support; domain and hosting billed at cost."),
    "ml": ("ലക്ഷ്യം: ബേക്കറി ഉൽപ്പന്നങ്ങൾ പ്രദർശിപ്പിക്കുകയും ഓൺലൈൻ ഓർഡറുകൾ സ്വീകരിക്കുകയും "
           "ചെയ്യുന്ന ആധുനിക വെബ്സൈറ്റ് തയ്യാറാക്കുക. പരിധി: ഹോം, മെനു, ഗാലറി, ഞങ്ങളെക്കുറിച്ച്, "
           "ബന്ധപ്പെടൽ എന്നിങ്ങനെ അഞ്ച് പേജുകൾ; ഓൺലൈൻ ഓർഡർ ഫോം; എല്ലാ പേജിലും വാട്ട്‌സ്ആപ്പ് "
           "ബട്ടൺ; മലയാളം-ഇംഗ്ലീഷ് ഉള്ളടക്കം. സമയപരിധി: ആദ്യ ആഴ്ച ഡിസൈൻ, രണ്ടാമത്തെ ആഴ്ച വികസനവും "
           "ഉള്ളടക്കവും; പതിനാല് പ്രവൃത്തി ദിവസത്തിനുള്ളിൽ ലോഞ്ച്. വിലനിർണ്ണയം: ഡിസൈൻ, വികസനം, "
           "അടിസ്ഥാന SEO, ഒരു മാസത്തെ പിന്തുണ എന്നിവയുൾപ്പെടെ ₹15,000 ഫിക്സഡ് പാക്കേജ്; ഡൊമെയിനും "
           "ഹോസ്റ്റിംഗും യഥാർത്ഥ ചെലവ്."),
    "hi": ("उद्देश्य: बेकरी उत्पादों को प्रदर्शित करने और ऑनलाइन ऑर्डर लेने वाली एक आधुनिक वेबसाइट "
           "बनाना। कार्यक्षेत्र: होम, मेन्यू, गैलरी, हमारे बारे में और संपर्क — पाँच पेज; ऑनलाइन "
           "ऑर्डर फॉर्म; हर पेज पर WhatsApp बटन; हिंदी-अंग्रेज़ी कंटेंट; मोबाइल-फर्स्ट डिज़ाइन। "
           "समय-सीमा: पहले सप्ताह में डिज़ाइन, दूसरे सप्ताह में डेवलपमेंट और कंटेंट लोडिंग; चौदह "
           "कार्य-दिवसों में टेस्टिंग और लॉन्च। मूल्य निर्धारण: डिज़ाइन, डेवलपमेंट, बुनियादी SEO "
           "सेटअप और एक माह के लॉन्च-बाद सहयोग सहित ₹15,000 का फिक्स्ड पैकेज; डोमेन और होस्टिंग "
           "वास्तविक लागत पर।"),
    "ta": ("நோக்கம்: பேக்கரி தயாரிப்புகளை காட்சிப்படுத்தி ஆன்லைன் ஆர்டர்களை பெறும் ஒரு நவீன "
           "வலைத்தளத்தை உருவாக்குவது. வரம்பு: ஹோம், மெனு, கேலரி, எங்களைப் பற்றி, தொடர்பு என "
           "ஐந்து பக்கங்கள்; ஆன்லைன் ஆர்டர் படிவம்; ஒவ்வொரு பக்கத்திலும் WhatsApp பட்டன்; தமிழ்-ஆங்கில "
           "உள்ளடக்கம்; மொபைல்-ஃபர்ஸ்ட் வடிவமைப்பு. கால அளவு: முதல் வாரம் வடிவமைப்பு, இரண்டாம் "
           "வாரம் உருவாக்கம் மற்றும் உள்ளடக்க ஏற்றம்; பதினான்கு வேலை நாட்களில் சோதனை மற்றும் லாஞ்ச். "
           "விலை நிர்ணயம்: வடிவமைப்பு, உருவாக்கம், அடிப்படை SEO அமைப்பு, ஒரு மாத லாஞ்ச்-பிந்தைய "
           "ஆதரவு உள்ளடக்கிய ₹15,000 நிலையான தொகை; டொமைன் மற்றும் ஹோஸ்டிங் உண்மையான செலவில்."),
}


def _canned_answers() -> dict[str, str]:
    """Prompt -> a passing answer, in bank order per (task, language)."""
    per_task_lang: dict[tuple[str, str], list[str]] = {}
    for lang in BENCHMARK_LANGUAGES:
        per_task_lang[("classification", lang)] = list(_CLASSIFICATION)
        per_task_lang[("translation", lang)] = list(_TRANSLATION[lang])
        per_task_lang[("summarization", lang)] = [_SUMMARY[lang]]
        per_task_lang[("requirements", lang)] = [_REQUIREMENTS[lang]]
        per_task_lang[("code_review", lang)] = [_CODE_REVIEW]
        per_task_lang[("proposal_draft", lang)] = [_PROPOSAL[lang]]
        per_task_lang[("qa_review", lang)] = [_QA_REVIEW]
    mapping: dict[str, str] = {}
    counters: dict[tuple[str, str], int] = {}
    for s in SCENARIOS:
        key = (s.task, s.language)
        idx = counters.get(key, 0)
        counters[key] = idx + 1
        mapping[s.prompt] = per_task_lang[key][idx]
    return mapping


def _good_client() -> httpx.Client:
    answers = _canned_answers()

    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.read())
        prompt = data["messages"][-1]["content"]
        # raw prompts from direct llm_complete calls (gate tests) need no
        # canned scenario answer — any completion content works there
        content = answers.get(prompt, "ok")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5)


def _bad_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "no idea"}}]})

    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5)


def _setup_provider(db, seed) -> None:
    register_candidate_providers(db, seed.tenant.id)
    _verify_provider(db, seed, PROVIDER, allowance=1000)


# --- runner --------------------------------------------------------------------


def test_run_benchmark_good_provider_passes(db, seed) -> None:
    _setup_provider(db, seed)
    card = run_benchmark(
        db, tenant_id=seed.tenant.id, provider=PROVIDER,
        http_client=_good_client(), settings=_settings(ai_provider_enabled=True),
    )
    db.commit()
    assert card["passed"] is True
    assert card["scenarios"] == 36
    assert card["overall_score"] == 1.0
    assert all(v["score"] == 1.0 for v in card["per_task"].values())
    assert card["per_language"]["ml"]["score"] == 1.0

    rows = list(db.scalars(select(ProviderQualityBenchmark)))
    assert len(rows) == 1
    assert rows[0].passed is True
    assert rows[0].benchmark_version == BENCHMARK_VERSION
    assert rows[0].provider == PROVIDER
    # no failure alert for a passing provider
    alerts = [r for r in db.scalars(select(NotificationOutbox))
              if r.template_key == "benchmark.failed"]
    assert alerts == []


def test_run_benchmark_bad_provider_fails_and_alerts(db, seed) -> None:
    _setup_provider(db, seed)
    card = run_benchmark(
        db, tenant_id=seed.tenant.id, provider=PROVIDER,
        http_client=_bad_client(), settings=_settings(ai_provider_enabled=True),
    )
    db.commit()
    assert card["passed"] is False
    assert card["per_task"]["classification"]["score"] == 0.0
    assert card["per_task"]["classification"]["failed"]  # scenario ids recorded

    rows = list(db.scalars(select(ProviderQualityBenchmark)))
    assert len(rows) == 1 and rows[0].passed is False
    alerts = [r for r in db.scalars(select(NotificationOutbox))
              if r.template_key == "benchmark.failed"]
    assert len(alerts) == 1
    assert PROVIDER in alerts[0].body
    assert "classification" in alerts[0].payload["failed_tasks"]


def test_run_benchmark_task_subset_and_validation(db, seed) -> None:
    _setup_provider(db, seed)
    card = run_benchmark(
        db, tenant_id=seed.tenant.id, provider=PROVIDER,
        tasks=["classification"], languages=["ml"],
        http_client=_good_client(), settings=_settings(ai_provider_enabled=True),
    )
    assert card["scenarios"] == 2
    assert set(card["per_task"]) == {"classification"}

    from app.core.errors import ConflictError

    with pytest.raises(ConflictError, match="unknown task"):
        run_benchmark(db, tenant_id=seed.tenant.id, provider=PROVIDER, tasks=["nope"],
                      http_client=_good_client(), settings=_settings(ai_provider_enabled=True))
    with pytest.raises(ConflictError, match="master switch"):
        run_benchmark(db, tenant_id=seed.tenant.id, provider=PROVIDER,
                      http_client=_good_client(), settings=_settings(ai_provider_enabled=False))


def test_run_benchmark_requires_registered_provider(db, seed) -> None:
    from app.core.errors import ConflictError

    with pytest.raises(ConflictError, match="no AI_LLM product"):
        run_benchmark(db, tenant_id=seed.tenant.id, provider="ghost",
                      http_client=_good_client(), settings=_settings(ai_provider_enabled=True))


def test_benchmark_reattempts_gated_provider(db, seed) -> None:
    """The gate must never block its own re-measurement (§6).

    Regression (live 2026-11-15): a gated provider's re-run recorded 0%
    built entirely from gate-blocked scenarios — self-referential evidence
    that locked the gate forever. A re-run with a healthy provider must
    actually measure and can lift the gate.
    """
    _setup_provider(db, seed)
    # 1. a bad run installs the gate
    card_bad = run_benchmark(
        db, tenant_id=seed.tenant.id, provider=PROVIDER,
        http_client=_bad_client(), settings=_settings(ai_provider_enabled=True),
    )
    db.commit()
    assert card_bad["passed"] is False

    # 2. production traffic on the failed task is gate-blocked
    blocked = llm_complete(
        db, tenant_id=seed.tenant.id, task="classification", prompt="ping",
        settings=_settings(ai_provider_enabled=True), http_client=_good_client(),
    )
    assert blocked.status == "PENDING_MANUAL"
    assert any("quality floor" in a["reason"] for a in blocked.attempts)

    # 3. the benchmark re-run must measure the provider, not the gate
    card_good = run_benchmark(
        db, tenant_id=seed.tenant.id, provider=PROVIDER,
        http_client=_good_client(), settings=_settings(ai_provider_enabled=True),
    )
    db.commit()
    assert card_good["passed"] is True
    assert all(v["score"] == 1.0 for v in card_good["per_task"].values())
    # no gate-blocked scenario may fake a quality verdict
    row_good = db.get(ProviderQualityBenchmark, card_good["record_id"])
    assert all(
        "quality floor" not in (r.get("failed_checks") or [""])[0]
        for r in row_good.score_json["scenario_results"]
    )

    # 4. the passing re-run lifts the gate for production traffic
    unblocked = llm_complete(
        db, tenant_id=seed.tenant.id, task="classification", prompt="ping",
        settings=_settings(ai_provider_enabled=True), http_client=_good_client(),
    )
    assert unblocked.status == "SUCCEEDED"


def test_throttled_run_is_inconclusive_and_does_not_poison_the_gate(db, seed) -> None:
    """A run answered mostly by provider 429s measures availability, not quality.

    Live case (2026-11-15): an openrouter re-run inside an upstream :free
    throttle window recorded 0% — all provider errors — and gated tasks the
    same provider had honestly passed hours earlier. Inconclusive rows must
    not overwrite the last conclusive verdict.
    """
    _setup_provider(db, seed)

    def _throttled(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    throttled = httpx.Client(transport=httpx.MockTransport(_throttled), timeout=5)

    card = run_benchmark(
        db, tenant_id=seed.tenant.id, provider=PROVIDER,
        http_client=throttled, settings=_settings(ai_provider_enabled=True),
    )
    db.commit()
    assert card["passed"] is False
    assert card["inconclusive"] is True
    assert card["provider_errors"] == card["scenarios"]
    row = db.get(ProviderQualityBenchmark, card["record_id"])
    assert row.score_json["inconclusive"] is True

    # the gate ignores the inconclusive row: no benchmark row ever PASSED,
    # so nothing gates — but crucially nothing FAILS on phantom 0% evidence
    # either; with a healthy provider the traffic flows normally
    ok = llm_complete(
        db, tenant_id=seed.tenant.id, task="classification", prompt="ping",
        settings=_settings(ai_provider_enabled=True), http_client=_good_client(),
    )
    assert ok.status == "SUCCEEDED"
    assert "quality floor" not in str(ok.attempts)


# --- §6 inference gate -----------------------------------------------------------


def test_gate_blocks_provider_for_failed_tasks_only(db, seed) -> None:
    _setup_provider(db, seed)
    # benchmark only classification, and fail it
    card = run_benchmark(
        db, tenant_id=seed.tenant.id, provider=PROVIDER, tasks=["classification"],
        http_client=_bad_client(), settings=_settings(ai_provider_enabled=True),
    )
    assert card["passed"] is False
    db.commit()

    result = llm_complete(
        db, tenant_id=seed.tenant.id, task="classification", prompt="classify this",
        target_provider=PROVIDER, http_client=_good_client(),
        settings=_settings(ai_provider_enabled=True),
    )
    assert result.status != "SUCCEEDED"
    assert "quality floor" in result.reason
    assert result.attempts and result.attempts[0]["status"] == "SKIPPED"

    # a task the benchmark did NOT cover stays eligible (no evidence against it)
    ok = llm_complete(
        db, tenant_id=seed.tenant.id, task="summarization", prompt="summarize this",
        target_provider=PROVIDER, http_client=_good_client(),
        settings=_settings(ai_provider_enabled=True),
    )
    assert ok.status == "SUCCEEDED"


def test_gate_allows_passed_unbenchmarked_and_stale(db, seed) -> None:
    _setup_provider(db, seed)
    settings = _settings(ai_provider_enabled=True)

    # 1) passing benchmark does not block
    run_benchmark(db, tenant_id=seed.tenant.id, provider=PROVIDER, tasks=["classification"],
                  http_client=_good_client(), settings=settings)
    db.commit()
    ok = llm_complete(db, tenant_id=seed.tenant.id, task="classification", prompt="x",
                      target_provider=PROVIDER, http_client=_good_client(), settings=settings)
    assert ok.status == "SUCCEEDED"

    # 2) a failed benchmark older than the freshness window stops gating
    product = _verify_provider(db, seed, PROVIDER, allowance=1000)
    db.add(ProviderQualityBenchmark(
        provider_product_id=product.id, provider=PROVIDER,
        benchmark_version=BENCHMARK_VERSION, tasks=["classification"], languages=["ml"],
        score_json={"per_task": {"classification": {"score": 0.0, "floor": 1.0,
                                                    "scenarios": 2, "passed": False,
                                                    "failed": []}}},
        passed=False, evaluated_at=utcnow() - timedelta(days=40),
    ))
    db.commit()
    assert benchmark_gate(db, product.id, "classification") is None
    ok = llm_complete(db, tenant_id=seed.tenant.id, task="classification", prompt="x",
                      target_provider=PROVIDER, http_client=_good_client(), settings=settings)
    assert ok.status == "SUCCEEDED"

    # 3) no benchmark row at all -> eligible (back-compat for existing pools)
    rows = list(db.scalars(select(ProviderQualityBenchmark)))
    for row in rows:
        db.delete(row)
    db.commit()
    ok = llm_complete(db, tenant_id=seed.tenant.id, task="classification", prompt="x",
                      target_provider=PROVIDER, http_client=_good_client(), settings=settings)
    assert ok.status == "SUCCEEDED"
