"""Aknja translation worker — self-hosted IndicTrans2-dist-200M shim (T-023).

OpenAI-compatible /v1/chat/completions endpoint in front of the two
IndicTrans2 dist-200M models (ai4bharat, MIT) on OCI instance-2, per the
docs/34 §3 decision. The app's inference layer reaches it through the
reverse SSH tunnel as http://127.0.0.1:8001 (docs/43).

Translation strategy — validated 8/8 against the app's benchmark evaluator
(scripts/t023b_worker_prototype.py, 2026-11-15):
- models unify Indic scripts to Devanagari: en->X output is post-converted
  to the target script (UnicodeIndicTransliterator), X->en source is
  pre-converted to Devanagari;
- brand terms are preserved verbatim: X->en injects the Latin brand into the
  source (glossary); en->X restores the Latin brand over the model's own
  transliteration (calibrated at startup, fuzzy/prefix-tolerant);
- prompts are parsed generically: source = last line after ': ', target =
  dominant script of the instruction part.

Non-translation prompts get HTTP 400 (translation-only worker): the app's
task-scoped routing never sends them, and a 400 is non-retryable there.
"""

from __future__ import annotations

import difflib
import os
import re
import threading

import torch
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from indicnlp.transliterate.unicode_transliterate import UnicodeIndicTransliterator
from pydantic import BaseModel
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

EN_INDIC = "ai4bharat/IndicTrans2-en-indic-dist-200M"
INDIC_EN = "ai4bharat/IndicTrans2-indic-en-dist-200M"
LANG2CODE = {"ml": "mal_Mlym", "hi": "hin_Deva", "ta": "tam_Taml", "en": "eng_Latn"}
INDIC_LANGS = ("ml", "hi", "ta")

# Terminology-preservation list (the benchmark instruction itself demands
# brand names rendered in Latin script exactly; this is the worker feature
# that enforces it). Extend as the brand inventory grows.
BRAND_TERMS = ["Aknja Digital", "WhatsApp"]
BRAND_GLOSSARY_ML = [  # source-side transliteration variants -> Latin brand
    ("അക്നജ ഡിജിറ്റൽ", "Aknja Digital"),
    ("അക്ഞ്ജ ഡിജിറ്റൽ", "Aknja Digital"),
    ("വാട്ട്\u200dസ്ആപ്പ്", "WhatsApp"),
    ("വാട്ട്\u200cസ്ആപ്പ്", "WhatsApp"),
    ("വാട്ട്സ്ആപ്പ്", "WhatsApp"),
]

WORKER_KEY = os.environ.get("AKNJA_WORKER_KEY", "")
NUM_BEAMS = int(os.environ.get("AKNJA_WORKER_BEAMS", "5"))

_SCRIPT_RANGES = {"ml": (0x0D00, 0x0D7F), "hi": (0x0900, 0x097F),
                  "ta": (0x0B80, 0x0BFF), "en": (0x0041, 0x007A)}

app = FastAPI(title="aknja-translate", version="1.0.0")
_lock = threading.Lock()  # torch inference is single-flight on 1 OCPU
_models: dict = {}
_ready = False


def detect_script(text: str) -> str:
    counts = {k: 0 for k in _SCRIPT_RANGES}
    for ch in text:
        cp = ord(ch)
        for lang, (lo, hi) in _SCRIPT_RANGES.items():
            if lo <= cp <= hi:
                counts[lang] += 1
                break
    counts.pop("en")
    best = max(counts, key=counts.get)
    return best if counts[best] >= 3 else "en"


def norm(tok: str) -> str:
    return re.sub(r"[\u200b\u200c\u200d]", "", tok)


def token_match(out_tok: str, stem_tok: str) -> bool:
    o, s = norm(out_tok), norm(stem_tok)
    if not o or not s:
        return False
    if o == s or (len(o) > len(s) and o.startswith(s)):
        return True  # exact, or stem + inflection suffix
    if difflib.SequenceMatcher(None, o, s).ratio() >= 0.72:
        return True
    k = max(3, len(s) - 2)
    return o[:k] == s[:k] and difflib.SequenceMatcher(None, o[:k], s[:k]).ratio() >= 0.8


def window_matches(window: list[str], stem_toks: list[str]) -> bool:
    if all(token_match(w, s) for w, s in zip(window, stem_toks)):
        return True
    if len(stem_toks) >= 2:  # tolerate spelling drift on the first token
        first = difflib.SequenceMatcher(None, norm(window[0]), norm(stem_toks[0])).ratio()
        return first >= 0.6 and all(
            token_match(w, s) for w, s in zip(window[1:], stem_toks[1:]))
    return False


def restore_brands(text: str, stems: dict[str, str]) -> str:
    toks = text.split()
    for brand, stem in stems.items():
        st = stem.split()
        i = 0
        while i <= len(toks) - len(st):
            if window_matches(toks[i:i + len(st)], st):
                toks[i:i + len(st)] = [brand]
                i += 1
            else:
                i += 1
    return " ".join(toks)


def to_target_script(deva_text: str, lang: str) -> str:
    if lang == "hi":
        return deva_text
    return UnicodeIndicTransliterator.transliterate(deva_text, "hi", lang)


def _load(which: str):
    mid = EN_INDIC if which == "en2indic" else INDIC_EN
    tok = AutoTokenizer.from_pretrained(mid, trust_remote_code=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(mid, trust_remote_code=True)
    model.eval()
    return tok, model


def _translate(which: str, text: str, src: str, tgt: str) -> str:
    tok, model = _models[which]
    batch = tok([f"{src} {tgt} {text}"], return_tensors="pt")
    with torch.inference_mode():
        gen = model.generate(**batch, num_beams=NUM_BEAMS, max_length=256)
    return tok.batch_decode(gen, skip_special_tokens=True)[0]


@app.on_event("startup")
def startup() -> None:
    global _ready
    for which in ("en2indic", "indic2en"):
        _models[which] = _load(which)
    # calibrate brand stems: the model's own isolated rendering per language
    _models["stems"] = {}
    for lang in INDIC_LANGS:
        _models["stems"][lang] = {}
        for brand in BRAND_TERMS:
            stem = to_target_script(
                _translate("en2indic", brand, "eng_Latn", LANG2CODE[lang]), lang)
            _models["stems"][lang][brand] = stem
    _ready = True


def parse_prompt(prompt: str) -> tuple[str, str]:
    """(target_lang, source) — marker-free, benchmark-instruction shaped."""
    lines = prompt.rstrip().split("\n")
    last = lines[-1]
    if ": " not in last:
        raise ValueError("no source sentence marker in the last line")
    source = last.split(": ", 1)[-1].strip()
    instruction = "\n".join(lines[:-1])
    if not source:
        raise ValueError("empty source sentence")
    return detect_script(instruction), source


def translate_request(prompt: str) -> str:
    target, source = parse_prompt(prompt)
    if target in INDIC_LANGS:
        raw = _translate("en2indic", source, "eng_Latn", LANG2CODE[target])
        out = to_target_script(raw, target)
        return restore_brands(out, _models["stems"][target])
    if target == "en":
        src_lang = detect_script(source)
        if src_lang not in INDIC_LANGS:
            raise ValueError(f"unsupported source language for->en: {src_lang!r}")
        glossed = source
        if src_lang == "ml":
            for ml, latin in BRAND_GLOSSARY_ML:
                glossed = glossed.replace(ml, f" {latin} ")
            glossed = re.sub(r"\s+", " ", glossed).strip()
        deva = UnicodeIndicTransliterator.transliterate(glossed, src_lang, "hi")
        out = _translate("indic2en", deva, LANG2CODE[src_lang], "eng_Latn")
        for b in BRAND_TERMS:
            out = re.sub(re.escape(b), b, out, flags=re.IGNORECASE)
        return out
    raise ValueError(f"unsupported target language: {target!r}")


class ChatRequest(BaseModel):
    model: str = ""
    messages: list[dict]
    temperature: float = 0.2


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok" if _ready else "loading", "models": sorted(_models)}


@app.post("/v1/chat/completions")
def chat_completions(body: ChatRequest, request: Request) -> dict:
    if WORKER_KEY and request.headers.get("Authorization") != f"Bearer {WORKER_KEY}":
        raise HTTPException(status_code=401, detail="bad worker key")
    if not _ready:
        raise HTTPException(status_code=503, detail="worker still loading models")
    user_texts = [m.get("content", "") for m in body.messages if m.get("role") == "user"]
    prompt = user_texts[-1] if user_texts else ""
    with _lock:
        try:
            text = translate_request(prompt)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"translation-only worker: {exc}")
    return {
        "id": "aknja-translate",
        "object": "chat.completion",
        "model": "indictrans2-dist-200M",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")
