"""LLM provider quality benchmark runner (v5.3.2 §5C + §6, docs/26 register).

What this module pins down:
- a versioned scenario bank: benchmark prompts with golden expectations for
  Malayalam, English, Hindi and Tamil across all seven task profiles;
- deterministic evaluators — schema/JSON validity, label match, named-entity
  preservation, target-script check, key-fact coverage, length bounds,
  required sections. Factuality beyond golden answers is NOT claimed: the
  benchmark enforces floors, it does not replace human review;
- quality floors per task: a provider below the floor for a task is not
  eligible for that task (§6: quality is a hard requirement, never traded
  for cost). The inference layer enforces this via `benchmark_gate`;
- one durable `provider_quality_benchmarks` row per run (§7) plus a founder
  alert on failure (docs/39 outbox).

Scoring is code-only arithmetic: scenario pass/fail -> per-task and
per-language ratios -> floor comparison. No LLM-judged scoring (circular).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.core.security import utcnow
from app.modules.ops.notifications import notify_admin
from app.modules.resources.models import ProviderQualityBenchmark

BENCHMARK_VERSION = "v1"
BENCHMARK_LANGUAGES = ("ml", "en", "hi", "ta")
BENCHMARK_FRESH_DAYS = 30  # older failed benchmarks stop gating (re-run instead)

# §6 quality floors per task profile. Structured tasks with golden labels
# (classification) and terminology-critical tasks (translation) demand a
# perfect score across all languages; generative tasks tolerate one weak
# language out of four (0.75).
QUALITY_FLOORS: dict[str, float] = {
    "classification": 1.0,
    "translation": 1.0,
    "summarization": 0.75,
    "requirements": 0.75,
    "code_review": 0.75,
    "proposal_draft": 0.75,
    "qa_review": 0.75,
}

# Unicode block per benchmark language, for the target-script check.
_SCRIPT_RANGES: dict[str, tuple[int, int]] = {
    "ml": (0x0D00, 0x0D7F),
    "hi": (0x0900, 0x097F),
    "ta": (0x0B80, 0x0BFF),
    "en": (0x0041, 0x007A),
}


@dataclass
class Scenario:
    task: str
    language: str
    prompt: str
    expect: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.task}.{self.language}.{_scenario_index(self)}"


def _scenario_index(s: Scenario) -> str:
    return str(SCENARIOS.index(s) + 1)


# --- instructions (one per task x language) -----------------------------------
# Self-contained prompts: every scenario carries its full instructions in the
# benchmark language, so a provider must follow instructions in that language.

_INSTR = {
    "classification": {
        "en": "Classify the support ticket below into exactly one category: BILLING, "
              "TECHNICAL, SCHEDULE, or OTHER. Output strict JSON only, in the form "
              '{"label": "CATEGORY"}.\n\nTicket: ',
        "ml": "താഴെയുള്ള സപ്പോർട്ട് ടിക്കറ്റ് BILLING, TECHNICAL, SCHEDULE, OTHER എന്നിവയിൽ "
              "ഒന്നായി തരംതിരിക്കുക. കൃത്യമായി {\"label\": \"CATEGORY\"} എന്ന രൂപത്തിൽ JSON മാത്രം "
              "നൽകുക.\n\nടിക്കറ്റ്: ",
        "hi": "नीचे दिए गए सपोर्ट टिकट को BILLING, TECHNICAL, SCHEDULE या OTHER — इनमें से एक "
              "श्रेणी में वर्गीकृत करें। केवल सख्त JSON दें: {\"label\": \"CATEGORY\"}.\n\nटिकट: ",
        "ta": "கீழே உள்ள சப்போர்ட் டிக்கெட்டை BILLING, TECHNICAL, SCHEDULE, OTHER என்பவற்றில் "
              "ஒன்றாக வகைப்படுத்துங்கள். கண்டிப்பாக {\"label\": \"CATEGORY\"} என்ற வடிவில் JSON "
              "மட்டும் தருங்கள்.\n\nடிக்கெட்: ",
    },
    "translation": {
        "en": "Translate the Malayalam sentence into professional English. Render brand "
              "names in Latin script exactly (Aknja Digital, WhatsApp). Output only the "
              "translation.\n\nSentence: ",
        "ml": "താഴെയുള്ള ഇംഗ്ലീഷ് വാക്യം മലയാളത്തിലേക്ക് വിവർത്തനം ചെയ്യുക. ബ്രാൻഡ് പേരുകൾ "
              "(Aknja Digital, WhatsApp) അതേപടി നിലനിർത്തുക. വിവർത്തനം മാത്രം ഔട്ട്പുട്ട് ചെയ്യുക.\n\nവാക്യം: ",
        "hi": "नीचे दिए गए अंग्रेज़ी वाक्य का हिंदी में अनुवाद करें। ब्रांड नाम (Aknja Digital, "
              "WhatsApp) यथावत रखें। केवल अनुवाद दें।\n\nवाक्य: ",
        "ta": "கீழே உள்ள ஆங்கில வாக்கியத்தை தமிழில் மொழிபெயர்க்கவும். பிராண்ட் பெயர்களை "
              "(Aknja Digital, WhatsApp) மாற்றாமல் வைக்கவும். மொழிபெயர்ப்பை மட்டும் தருக.\n\nவாக்கியம்: ",
    },
    "summarization": {
        "en": "Summarize the project update below in at most 40 words. Keep the key facts "
              "and dates. Output only the summary.\n\nUpdate: ",
        "ml": "താഴെയുള്ള പ്രോജക്ട് അപ്ഡേറ്റ് 40 വാക്കിൽ കൂടാതെ ചുരുക്കി എഴുതുക. പ്രധാന "
              "വസ്തുതകളും തീയതികളും നിലനിർത്തുക. ചുരുക്കം മാത്രം നൽകുക.\n\nഅപ്ഡേറ്റ്: ",
        "hi": "नीचे दिए गए प्रोजेक्ट अपडेट को अधिकतम 40 शब्दों में संक्षेप में लिखें। मुख्य "
              "तथ्य और तारीखें बनाए रखें। केवल सारांश दें।\n\nअपडेट: ",
        "ta": "கீழே உள்ள திட்ட புதுப்பிப்பை 40 சொற்களுக்கு மிகாமல் சுருக்கமாக எழுதுங்கள். "
              "முக்கிய தகவல்களையும் தேதிகளையும் காத்திருங்கள். சுருக்கத்தை மட்டும் தருங்கள்.\n\nபுதுப்பிப்பு: ",
    },
    "requirements": {
        "en": "Extract the client requirements from the request below as a strict JSON "
              'array of at least three items, each {"id": "R1", "text": "..."}. Output '
              "only the JSON.\n\nRequest: ",
        "ml": "താഴെയുള്ള ക്ലയന്റ് അഭ്യർത്ഥനയിൽ നിന്ന് ആവശ്യകതകൾ വേർതിരിച്ചെടുത്ത് കൃത്യമായി "
              "{\"id\": \"R1\", \"text\": \"...\"} എന്ന രൂപത്തിൽ കുറഞ്ഞത് മൂന്ന് ഇനമുള്ള JSON അറേ "
              "ആയി നൽകുക. JSON മാത്രം ഔട്ട്പുട്ട് ചെയ്യുക.\n\nഅഭ്യർത്ഥന: ",
        "hi": "नीचे दिए गए क्लाइंट अनुरोध से आवश्यकताएँ निकालकर केवल सख्त JSON ऐरे दें — कम से कम "
              "तीन आइटम, प्रत्येक {\"id\": \"R1\", \"text\": \"...\"}.\n\nअनुरोध: ",
        "ta": "கீழே உள்ள கிளையன்ட் கோரிக்கையிலிருந்து தேவைகளை பிரித்தெடுத்து, குறைந்தது மூன்று "
              "உருப்படிகள் கொண்ட {\"id\": \"R1\", \"text\": \"...\"} வடிவில் JSON அணியை மட்டும் "
              "தருங்கள்.\n\nகோரிக்கை: ",
    },
    "code_review": {
        "en": "Review the JavaScript snippet below for defects. Output strict JSON only: "
              '{"findings": [{"severity": "high|medium|low", "comment": "..."}]}.\n\nCode: ',
        "ml": "താഴെയുള്ള JavaScript കോഡ് റിവ്യൂ ചെയ്യുക. കൃത്യമായി {\"findings\": "
              "[{\"severity\": \"high|medium|low\", \"comment\": \"...\"}]} എന്ന JSON മാത്രം "
              "നൽകുക.\n\nകോഡ്: ",
        "hi": "नीचे दिए गए JavaScript स्निपेट की खामियों की समीक्षा करें। केवल सख्त JSON दें: "
              '{"findings": [{"severity": "high|medium|low", "comment": "..."}]}.\n\nकोड: ',
        "ta": "கீழே உள்ள JavaScript குறியீட்டை மேலோட்டமாக ஆய்வு செய்து, {\"findings\": "
              "[{\"severity\": \"high|medium|low\", \"comment\": \"...\"}]} என்ற JSON ஐ மட்டும் "
              "தருங்கள்.\n\nகுறியீடு: ",
    },
    "proposal_draft": {
        "en": "Draft a short website proposal for a bakery client. Budget: ₹15,000. "
              "Timeline: 2 weeks. Include these four sections with these exact headings: "
              "Objective, Scope, Timeline, Pricing. Output only the proposal text.\n\nBrief: ",
        "ml": "ഒരു ബേക്കറി ക്ലയന്റിനായി ചെറിയ വെബ്സൈറ്റ് പ്രപ്പസൽ തയ്യാറാക്കുക. ബജറ്റ്: ₹15,000. "
              "സമയപരിധി: 2 ആഴ്ച. ഈ നാല് സെക്ഷനുകൾ ഈ തലക്കെട്ടുകളിൽ ഉൾപ്പെടുത്തുക: ലക്ഷ്യം, പരിധി, "
              "സമയപരിധി, വിലനിർണ്ണയം. പ്രപ്പസൽ ടെക്സ്റ്റ് മാത്രം നൽകുക.\n\nബ്രീഫ്: ",
        "hi": "एक बेकरी क्लाइंट के लिए एक छोटा वेबसाइट प्रपोज़ल तैयार करें। बजट: ₹15,000. "
              "समय-सीमा: 2 सप्ताह। इन चार सेक्शन इन्हीं शीर्षकों के साथ शामिल करें: उद्देश्य, "
              "कार्यक्षेत्र, समय-सीमा, मूल्य निर्धारण। केवल प्रपोज़ल टेक्स्ट दें।\n\nब्रीफ: ",
        "ta": "ஒரு பேக்கரி கிளையன்டுக்கான சிறிய வலைத்தள முன்மொழிவை தயார் செய்யுங்கள். பட்ஜெட்: "
              "₹15,000. கால அளவு: 2 வாரங்கள். இந்த நான்கு பகுதிகளையும் இதே தலைப்புகளில் "
              "சேர்க்கவும்: நோக்கம், வரம்பு, கால அளவு, விலை நிர்ணயம். முன்மொழிவு உரையை மட்டும் "
              "தருங்கள்.\n\nசுருக்கம்: ",
    },
    "qa_review": {
        "en": "Review the QA report below and decide whether the release passes. Output "
              'strict JSON only: {"passed": true|false, "issues": [{"severity": '
              '"high|medium|low", "description": "..."}]}.\n\nReport: ',
        "ml": "താഴെയുള്ള QA റിപ്പോർട്ട് പരിശോധിച്ച് റിലീസ് പാസാകുമോ എന്ന് തീരുമാനിക്കുക. "
              "കൃത്യമായി {\"passed\": true|false, \"issues\": [{\"severity\": \"high|medium|low\", "
              "\"description\": \"...\"}]} എന്ന JSON മാത്രം നൽകുക.\n\nറിപ്പോർട്ട്: ",
        "hi": "नीचे दी गई QA रिपोर्ट की समीक्षा करके तय करें कि रिलीज़ पास होगी या नहीं। केवल सख्त "
              'JSON दें: {"passed": true|false, "issues": [{"severity": "high|medium|low", '
              '"description": "..."}]}.\n\nरिपोर्ट: ',
        "ta": "கீழே உள்ள QA அறிக்கையை மேலோட்டமாக ஆய்ந்து, வெளியீடு தேர்ச்சி பெறுமா என்று "
              "முடிவு செய்யுங்கள். {\"passed\": true|false, \"issues\": [{\"severity\": "
              "\"high|medium|low\", \"description\": \"...\"}]} என்ற JSON ஐ மட்டும் தருங்கள்.\n\nஅறிக்கை: ",
    },
}

_TICKETS = {
    ("classification", "en"): [
        ("My monthly invoice shows a double charge for the hosting plan. Please correct it.", "BILLING"),
        ("The client portal login page returns a 500 error since this morning.", "TECHNICAL"),
    ],
    ("classification", "ml"): [
        ("ഈ മാസത്തെ ഇൻവോയ്സിൽ ഹോസ്റ്റിംഗ് പ്ലാനായി രണ്ട് തവണ തുക അടിച്ചിരിക്കുന്നു. ദയവായി തിരുത്തുക.", "BILLING"),
        ("ക്ലയന്റ് പോർട്ടൽ ലോഗിൻ പേജിൽ ഇന്ന് രാവിലെ മുതൽ 500 പിശക് കാണിക്കുന്നു.", "TECHNICAL"),
    ],
    ("classification", "hi"): [
        ("इस महीने के इनवॉइस में होस्टिंग प्लान की रकम दो बार जोड़ी गई है। कृपया ठीक कर दें।", "BILLING"),
        ("क्लाइंट पोर्टल के लॉगिन पेज पर आज सुबह से 500 एरर आ रहा है।", "TECHNICAL"),
    ],
    ("classification", "ta"): [
        ("இந்த மாத இன்வாய்ஸில் ஹோஸ்டிங் திட்டத்தின் தொகை இருமுறை சேர்க்கப்பட்டுள்ளது. தயவுசெய்து சரிசெய்யவும்.", "BILLING"),
        ("கிளையன்ட் போர்டல் லாகின் பக்கத்தில் இன்று காலை முதல் 500 பிழை வருகிறது.", "TECHNICAL"),
    ],
}

# Translation sources: target language -> [(source sentence, entities)]
_TRANSLATIONS = {
    "en": [
        ("അക്നജ ഡിജിറ്റൽ അടുത്ത വെള്ളിയാഴ്ച പുതിയ ക്ലയന്റ് പോർട്ടൽ അവതരിപ്പിക്കും.", ["Aknja Digital"]),
        ("തിങ്കളാഴ്ചയ്ക്ക് മുമ്പ് വാട്ട്‌സ്ആപ്പിൽ പേയ്മെന്റ് ഗേറ്റ്വേ ഇന്റഗ്രേഷൻ ഉറപ്പാക്കുക.", ["WhatsApp"]),
    ],
    "ml": [
        ("Aknja Digital will launch the new client portal next Friday.", ["Aknja Digital"]),
        ("Please confirm the payment gateway integration on WhatsApp before Monday.", ["WhatsApp"]),
    ],
    "hi": [
        ("Aknja Digital will launch the new client portal next Friday.", ["Aknja Digital"]),
        ("Please confirm the payment gateway integration on WhatsApp before Monday.", ["WhatsApp"]),
    ],
    "ta": [
        ("Aknja Digital will launch the new client portal next Friday.", ["Aknja Digital"]),
        ("Please confirm the payment gateway integration on WhatsApp before Monday.", ["WhatsApp"]),
    ],
}

_UPDATES = {
    "en": "This week we finished the client portal design. Payment gateway testing is "
          "pending. The launch date is fixed for March 10. The content writer is available.",
    "ml": "ഈ ആഴ്ച ഞങ്ങൾ ക്ലയന്റ് പോർട്ടലിന്റെ ഡിസൈൻ തയ്യാറാക്കി. പേയ്മെന്റ് ഗേറ്റ്വേ ടെസ്റ്റിംഗ് "
          "ബാക്കിയുണ്ട്. ലോഞ്ച് തീയതി മാർച്ച് 10 ആയി നിശ്ചയിച്ചു. ഉള്ളടക്ക എഴുത്തുകാരൻ ലഭ്യമാണ്.",
    "hi": "इस सप्ताह हमने क्लाइंट पोर्टल का डिज़ाइन पूरा किया। पेमेंट गेटवे की टेस्टिंग बाकी है। "
          "लॉन्च की तारीख 10 मार्च तय हुई। कंटेंट राइटर उपलब्ध हैं।",
    "ta": "இந்த வாரம் கிளையன்ட் போர்டல் வடிவமைப்பை முடித்தோம். பேமெண்ட் கேட்வே சோதனை "
          "மீதமுள்ளது. லாஞ்ச் தேதி மார்ச் 10 ஆக நிர்ணயிக்கப்பட்டது. கண்டென்ட் எழுத்தாளர் கிடைக்கிறார்.",
}

_SUMMARY_TERMS = {
    "en": ["payment gateway", "March 10"],
    "ml": ["പേയ്മെന്റ് ഗേറ്റ്വേ", "മാർച്ച് 10"],
    "hi": ["पेमेंट गेटवे", "10 मार्च"],
    "ta": ["பேமெண்ட் கேட்வே", "மார்ச் 10"],
}

_REQUIREMENTS = {
    "en": (("We need a bakery website with an online order form, a WhatsApp button on "
            "every page, Tamil language support, and a gallery for cake photos."),
           ["order", "gallery"]),
    "ml": (("ബേക്കറി വെബ്സൈറ്റ് വേണം: ഓൺലൈൻ ഓർഡർ ഫോം, എല്ലാ പേജിലും വാട്ട്‌സ്ആപ്പ് ബട്ടൺ, "
            "തമിഴ് ഭാഷാ പിന്തുണ, കേക്ക് ഫോട്ടോ ഗാലറി."), ["ഓർഡർ", "ഗാലറി"]),
    "hi": (("हमें बेकरी वेबसाइट चाहिए: ऑनलाइन ऑर्डर फॉर्म, हर पेज पर WhatsApp बटन, तमिल भाषा "
            "समर्थन, और केक फोटो की गैलरी।"), ["ऑर्डर", "गैलरी"]),
    "ta": (("நமக்கு பேக்கரி வலைத்தளம் வேண்டும்: ஆன்லைன் ஆர்டர் படிவம், ஒவ்வொரு பக்கத்திலும் "
            "WhatsApp பட்டன், தமிழ் மொழி ஆதரவு, கேக் புகைப்பட கேலரி."), ["ஆர்டர்", "கேலரி"]),
}

_CODE_SNIPPET = (
    "function greet(user) {\n  return \"Hello, \" + user.profile.name + \"!\";\n}"
)

_QA_REPORTS = {
    "en": "QA report: login works; dashboard loads; the Download invoice link returns "
          "404 on Chrome.",
    "ml": "QA റിപ്പോർട്ട്: ലോഗിൻ പ്രവർത്തിക്കുന്നു; ഡാഷ്ബോർഡ് ലോഡ് ചെയ്യുന്നു; Download invoice "
          "ലിങ്ക് Chrome-ൽ 404 കാണിക്കുന്നു.",
    "hi": "QA रिपोर्ट: लॉगिन काम कर रहा है; डैशबोर्ड लोड होता है; Download invoice लिंक Chrome "
          "पर 404 दे रहा है।",
    "ta": "QA அறிக்கை: லாகின் வேலை செய்கிறது; டாஷ்போர்டு ஏற்றப்படுகிறது; Download invoice "
          "லிங்க் Chrome-இல் 404 காட்டுகிறது.",
}

_PROPOSAL_BRIEFS = {
    "en": "Bakery in Kochi needs a website to show cakes and take orders online.",
    "ml": "കൊച്ചിയിലെ ഒരു ബേക്കറിക്ക് കേക്കുകൾ കാണിക്കാനും ഓൺലൈനിൽ ഓർഡർ സ്വീകരിക്കാനും വെബ്സൈറ്റ് വേണം.",
    "hi": "कोच्चि की एक बेकरी को केक दिखाने और ऑनलाइन ऑर्डर लेने के लिए वेबसाइट चाहिए।",
    "ta": "கொச்சியில் உள்ள ஒரு பேக்கரிக்கு கேக்குகளை காட்டவும் ஆன்லைனில் ஆர்டர் பெறவும் ஒரு "
          "வலைத்தளம் தேவை.",
}

_PROPOSAL_SECTIONS = {
    "en": ["Objective", "Scope", "Timeline", "Pricing"],
    "ml": ["ലക്ഷ്യം", "പരിധി", "സമയപരിധി", "വിലനിർണ്ണയം"],
    "hi": ["उद्देश्य", "कार्यक्षेत्र", "समय-सीमा", "मूल्य निर्धारण"],
    "ta": ["நோக்கம்", "வரம்பு", "கால அளவு", "விலை நிர்ணயம்"],
}


def _build_scenarios() -> list[Scenario]:
    bank: list[Scenario] = []
    for lang in BENCHMARK_LANGUAGES:
        for text, label in _TICKETS[("classification", lang)]:
            bank.append(Scenario(
                "classification", lang, _INSTR["classification"][lang] + text,
                {"json": True, "label": label},
            ))
        for source, entities in _TRANSLATIONS[lang]:
            bank.append(Scenario(
                "translation", lang, _INSTR["translation"][lang] + source,
                {"entities": entities, "script": lang, "min_words": 4},
            ))
        bank.append(Scenario(
            "summarization", lang, _INSTR["summarization"][lang] + _UPDATES[lang],
            {"must_include": _SUMMARY_TERMS[lang], "min_words": 8, "max_words": 60,
             "source": _UPDATES[lang]},
        ))
        req_text, req_terms = _REQUIREMENTS[lang]
        bank.append(Scenario(
            "requirements", lang, _INSTR["requirements"][lang] + req_text,
            {"json": True, "min_items": 3, "must_include": req_terms},
        ))
        bank.append(Scenario(
            "code_review", lang, _INSTR["code_review"][lang] + _CODE_SNIPPET,
            {"json": True, "min_findings": 1, "must_include": ["user.profile"]},
        ))
        bank.append(Scenario(
            "proposal_draft", lang, _INSTR["proposal_draft"][lang] + _PROPOSAL_BRIEFS[lang],
            {"sections": _PROPOSAL_SECTIONS[lang], "min_words": 50, "max_words": 500},
        ))
        bank.append(Scenario(
            "qa_review", lang, _INSTR["qa_review"][lang] + _QA_REPORTS[lang],
            {"json": True, "passed": False, "min_issues": 1, "must_include": ["404"]},
        ))
    return bank


SCENARIOS: list[Scenario] = _build_scenarios()


# --- deterministic evaluators --------------------------------------------------


def _extract_json(text: str):
    """Parse the first JSON object/array in a response; None on failure."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = min(
        (i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0), default=-1
    )
    if start < 0:
        return None
    for end_char, end_idx in (("}", cleaned.rfind("}")), ("]", cleaned.rfind("]"))):
        if end_idx > start:
            try:
                return json.loads(cleaned[start : end_idx + 1])
            except ValueError:
                continue
    return None


def _letters(text: str) -> list[str]:
    return [c for c in text if c.isalpha()]


def _script_ratio(text: str, language: str) -> float:
    """Share of letters inside the language's Unicode block."""
    lo, hi = _SCRIPT_RANGES[language]
    letters = _letters(text)
    if not letters:
        return 0.0
    inside = sum(1 for c in letters if lo <= ord(c) <= hi)
    return inside / len(letters)


def _evaluate(task: str, text: str, expect: dict) -> list[str]:
    """Return the list of failed checks ([] means the scenario passed)."""
    lowered = text.lower()
    failed: list[str] = []
    if not text or not text.strip():
        return ["empty response"]

    if task == "classification":
        data = _extract_json(text)
        if not isinstance(data, dict):
            return ["invalid JSON"]
        if data.get("label") != expect["label"]:
            failed.append(f"label mismatch: got {data.get('label')!r}, want {expect['label']!r}")

    elif task == "translation":
        for entity in expect["entities"]:
            if entity.lower() not in lowered:
                failed.append(f"entity lost: {entity}")
        if _script_ratio(text, expect["script"]) < 0.5:
            failed.append(f"wrong script: <50% {expect['script']} letters")
        if len(text.split()) < expect.get("min_words", 1):
            failed.append("too short")

    elif task == "summarization":
        for term in expect["must_include"]:
            if term.lower() not in lowered:
                failed.append(f"key fact lost: {term}")
        words = len(text.split())
        if words < expect.get("min_words", 1):
            failed.append("summary too short")
        if words > expect.get("max_words", 10_000):
            failed.append("summary too long (instruction adherence)")
        if " ".join(text.split()) == " ".join(expect["source"].split()):
            failed.append("verbatim copy of source")

    elif task == "requirements":
        data = _extract_json(text)
        if not isinstance(data, list):
            return ["invalid JSON array"]
        if len(data) < expect.get("min_items", 3):
            failed.append(f"fewer than {expect['min_items']} requirements")
        if not all(isinstance(i, dict) and str(i.get("text", "")).strip() for i in data):
            failed.append("requirement items missing 'text'")
        for term in expect.get("must_include", []):
            if term.lower() not in lowered:
                failed.append(f"requirement lost: {term}")

    elif task == "code_review":
        data = _extract_json(text)
        if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
            return ["invalid JSON"]
        if len(data["findings"]) < expect.get("min_findings", 1):
            failed.append("no findings reported")
        for term in expect.get("must_include", []):
            if term.lower() not in lowered:
                failed.append(f"defect not identified: {term}")

    elif task == "proposal_draft":
        for section in expect["sections"]:
            if section.lower() not in lowered:
                failed.append(f"missing section: {section}")
        words = len(text.split())
        if words < expect.get("min_words", 1):
            failed.append("proposal too short")
        if words > expect.get("max_words", 10_000):
            failed.append("proposal too long")

    elif task == "qa_review":
        data = _extract_json(text)
        if not isinstance(data, dict):
            return ["invalid JSON"]
        if data.get("passed") is not expect["passed"]:
            failed.append(f"verdict mismatch: got {data.get('passed')}, want {expect['passed']}")
        issues = data.get("issues")
        if not isinstance(issues, list) or len(issues) < expect.get("min_issues", 1):
            failed.append("issues list missing or empty")
        for term in expect.get("must_include", []):
            if term.lower() not in lowered:
                failed.append(f"defect not identified: {term}")

    return failed


# --- runner ---------------------------------------------------------------------


def run_benchmark(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    tasks: list[str] | None = None,
    languages: list[str] | None = None,
    http_client=None,
    settings=None,
) -> dict:
    """Run the scenario bank against ONE provider (no failover) and record it.

    Raises ConflictError when the AI master switch is off or the provider has
    no registered AI_LLM product — a benchmark that cannot actually egress
    must not fabricate scores.
    """
    # Imported here to avoid a circular import (inference imports the gate).
    from app.core.config import get_settings
    from app.modules.ai.inference import TASK_PROFILES, _target_product, llm_complete

    cfg = settings or get_settings()
    if not cfg.ai_provider_enabled:
        raise ConflictError("AI_PROVIDER_ENABLED=false — enable the master switch first")
    pair = _target_product(db, tenant_id, provider)
    if pair is None:
        raise ConflictError(
            f"provider '{provider}' has no AI_LLM product registered — "
            "run register-provider-candidates / verify-provider first"
        )
    product, account = pair

    selected_tasks = list(tasks or TASK_PROFILES.keys())
    unknown = [t for t in selected_tasks if t not in TASK_PROFILES]
    if unknown:
        raise ConflictError(f"unknown task(s): {unknown}")
    selected_languages = list(languages or BENCHMARK_LANGUAGES)
    unknown_langs = [l for l in selected_languages if l not in BENCHMARK_LANGUAGES]
    if unknown_langs:
        raise ConflictError(f"unknown language(s): {unknown_langs}")

    scenarios = [
        s for s in SCENARIOS
        if s.task in selected_tasks and s.language in selected_languages
    ]
    results: list[dict] = []
    for s in scenarios:
        outcome = llm_complete(
            db, tenant_id=tenant_id, task=s.task, prompt=s.prompt,
            target_provider=provider, http_client=http_client, settings=cfg,
            # The gate is fed by this very measurement — a gated provider
            # must still be re-measurable (else a single bad row locks
            # forever with self-referential 0% evidence; live 2026-11-15).
            bypass_quality_gate=True,
        )
        if outcome.status != "SUCCEEDED":
            results.append({
                "scenario": s.id, "task": s.task, "language": s.language,
                "passed": False, "failed_checks": [f"provider error: {outcome.reason[:200]}"],
                "latency_ms": outcome.latency_ms,
            })
            continue
        failed_checks = _evaluate(s.task, outcome.text, s.expect)
        results.append({
            "scenario": s.id, "task": s.task, "language": s.language,
            "passed": not failed_checks, "failed_checks": failed_checks,
            "latency_ms": outcome.latency_ms,
        })

    per_task: dict[str, dict] = {}
    for task in selected_tasks:
        task_results = [r for r in results if r["task"] == task]
        if not task_results:
            continue
        score = sum(1 for r in task_results if r["passed"]) / len(task_results)
        floor = QUALITY_FLOORS[task]
        per_task[task] = {
            "score": round(score, 4), "floor": floor, "scenarios": len(task_results),
            "passed": score >= floor,
            "failed": [r["scenario"] for r in task_results if not r["passed"]],
        }
    per_language: dict[str, dict] = {}
    for lang in selected_languages:
        lang_results = [r for r in results if r["language"] == lang]
        if lang_results:
            per_language[lang] = {
                "score": round(sum(1 for r in lang_results if r["passed"]) / len(lang_results), 4),
                "scenarios": len(lang_results),
            }
    overall = (
        round(sum(t["score"] for t in per_task.values()) / len(per_task), 4)
        if per_task else 0.0
    )
    passed = bool(per_task) and all(t["passed"] for t in per_task.values())
    latencies = [r["latency_ms"] for r in results if r["latency_ms"]]

    # Availability vs quality (live 2026-11-15): when most scenarios never
    # got an answer (429/timeout provider errors — e.g. an upstream :free
    # throttle window), the 0% measures AVAILABILITY, not model quality.
    # Mark the row inconclusive: it stays as honest evidence but the gate
    # skips it and keeps the last conclusive verdict.
    provider_errors = sum(
        1 for r in results
        if r["failed_checks"] and str(r["failed_checks"][0]).startswith("provider error")
    )
    inconclusive = bool(results) and provider_errors / len(results) >= 0.5

    row = ProviderQualityBenchmark(
        provider_product_id=product.id,
        provider=account.provider,
        benchmark_version=BENCHMARK_VERSION,
        tasks=selected_tasks,
        languages=selected_languages,
        score_json={
            "per_task": per_task, "per_language": per_language,
            "overall_score": overall, "scenario_results": results,
            "inconclusive": inconclusive,
            "provider_errors": provider_errors,
            "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
        },
        passed=passed,
        evaluated_at=utcnow(),
    )
    db.add(row)
    db.flush()

    if not passed:
        failed_tasks = [t for t, v in per_task.items() if not v["passed"]]
        notify_admin(
            db,
            template_key="benchmark.failed",
            payload={
                "provider": account.provider,
                "failed_tasks": ", ".join(failed_tasks),
                "overall_score": f"{overall:.0%}",
            },
            idempotency_key=f"benchmark.failed:{account.provider}:{BENCHMARK_VERSION}"
                            f":{utcnow():%Y%m%d}",
            tenant_id=tenant_id,
        )

    return {
        "record_id": str(row.id),
        "provider": account.provider,
        "benchmark_version": BENCHMARK_VERSION,
        "tasks": selected_tasks,
        "languages": selected_languages,
        "scenarios": len(results),
        "passed": passed,
        "overall_score": overall,
        "per_task": per_task,
        "per_language": per_language,
        "inconclusive": inconclusive,
        "provider_errors": provider_errors,
    }


def benchmark_gate(db: Session, product_id: uuid.UUID, task: str) -> str | None:
    """Return a blocking reason if the latest fresh benchmark failed this task.

    None means eligible: no benchmark row, a passed benchmark, a benchmark
    that did not cover this task, or one older than BENCHMARK_FRESH_DAYS
    (stale evidence must not gate forever — re-run the benchmark instead).

    INCONCLUSIVE rows (a run whose scenarios were mostly provider errors —
    e.g. an upstream :free throttle window, live 2026-11-15) are skipped:
    they measure availability, not quality, and must not overwrite the last
    honest verdict with a self-referential 0%.
    """
    from datetime import timedelta

    rows = db.scalars(
        select(ProviderQualityBenchmark)
        .where(ProviderQualityBenchmark.provider_product_id == product_id)
        .order_by(ProviderQualityBenchmark.evaluated_at.desc())
        .limit(5)
    ).all()
    row = next((r for r in rows if not (r.score_json or {}).get("inconclusive")), None)
    if row is None or row.passed:
        return None
    if row.evaluated_at < utcnow() - timedelta(days=BENCHMARK_FRESH_DAYS):
        return None
    entry = (row.score_json or {}).get("per_task", {}).get(task)
    if entry is None or entry.get("passed", True):
        return None
    return (
        f"quality floor (benchmark {row.benchmark_version}): task '{task}' scored "
        f"{entry.get('score', 0):.2f} < floor {entry.get('floor', 0):.2f}"
    )
