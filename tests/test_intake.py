"""Unified intake pipeline tests (docs/34, T-027)."""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from app.core.enums import UserRole
from app.modules.crm.models import Lead
from app.modules.identity.service import Principal
from app.modules.intake import service as intake
from app.modules.intake.models import IntakeMessage
from app.modules.ops.models import NotificationOutbox


def _principal(seed) -> Principal:
    return Principal(user_id=seed.admin.id, email=seed.admin.email,
                     tenant_id=seed.tenant.id, role=UserRole.SUPER_ADMIN,
                     client_id=None, session_id=seed.admin.id, csrf_token="t")


def _ai(status, text):
    return SimpleNamespace(status=status, text=text, provider="gemini",
                           reason="no eligible provider" if status != "SUCCEEDED" else "")


_CLASSIFIED = ('{"is_project_inquiry": true, "service_domain": "SOFTWARE_ENGINEERING", '
              '"language": "en", "urgency": "normal", "summary": "wants a bakery app"}')
_EXTRACTED = ('{"requirements": ["PWA ordering app", "WhatsApp notifications"], '
              '"missing_info": ["budget", "deadline"], "suggested_title": "Bakery Ordering App"}')


def test_inquiry_converts_to_lead_with_full_provenance(db, seed, monkeypatch):
    import app.modules.intake.service as svc
    calls = []

    def fake_llm(db, *, tenant_id, task, prompt, **kw):
        calls.append(task)
        return _ai("SUCCEEDED", _CLASSIFIED if task == "classification" else _EXTRACTED)

    monkeypatch.setattr(svc, "llm_complete", fake_llm)
    msg = intake.submit_intake_message(
        db, principal=_principal(seed), channel="MANUAL",
        sender="beena@example.com", content="I need a bakery ordering app "
        "with WhatsApp notifications for my shop in Kozhikode.")
    db.commit()

    assert calls == ["classification", "requirements"]
    assert msg.status == "CONVERTED" and msg.lead_id is not None
    assert msg.ai_classification["summary"] == "wants a bakery app"
    assert msg.ai_extraction["requirements"][0] == "PWA ordering app"
    # raw responses kept verbatim for §3 transparency
    assert _CLASSIFIED.startswith('{"is_project_inquiry"') or \
        "is_project_inquiry" in msg.ai_classification["raw_response"]

    lead = db.get(Lead, msg.lead_id)
    assert lead.source == "MANUAL" and lead.contact_email == "beena@example.com"
    assert "WhatsApp notifications" in lead.description
    # admin notified exactly once (idempotent outbox row)
    note = db.scalars(select(NotificationOutbox).where(
        NotificationOutbox.template_key == "intake.received")).all()
    assert len(note) == 1


def test_non_inquiry_rejected_without_lead(db, seed, monkeypatch):
    import app.modules.intake.service as svc

    monkeypatch.setattr(svc, "llm_complete", lambda *a, **k: _ai(
        "SUCCEEDED", '{"is_project_inquiry": false, "service_domain": "OTHER", '
                     '"summary": "asking about opening hours"}'))
    msg = intake.submit_intake_message(
        db, principal=_principal(seed), channel="MANUAL", sender="ravi",
        content="What time do you open tomorrow?")
    db.commit()
    assert msg.status == "REJECTED" and msg.lead_id is None
    assert db.scalar(select(Lead).where(Lead.source == "MANUAL")) is None


def test_ai_unavailable_needs_review_fail_closed(db, seed, monkeypatch):
    import app.modules.intake.service as svc

    monkeypatch.setattr(svc, "llm_complete", lambda *a, **k: _ai(
        "PENDING_MANUAL", ""))
    msg = intake.submit_intake_message(
        db, principal=_principal(seed), channel="EMAIL", sender="x@y.com",
        content="Please build me a website.")
    db.commit()
    assert msg.status == "NEEDS_REVIEW" and msg.lead_id is None
    assert "classification unavailable" in msg.notes
    # no phantom leads, but the record survives for later reprocessing
    assert msg.raw_content == "Please build me a website."


def test_unparseable_classification_needs_review(db, seed, monkeypatch):
    import app.modules.intake.service as svc

    monkeypatch.setattr(svc, "llm_complete", lambda *a, **k: _ai(
        "SUCCEEDED", "I could not classify this properly."))
    msg = intake.submit_intake_message(
        db, principal=_principal(seed), channel="MANUAL", sender="z",
        content="some message")
    db.commit()
    assert msg.status == "NEEDS_REVIEW"
    assert msg.ai_classification.get("parse_error") is True


def test_reprocess_keeps_original_and_creates_fresh_row(db, seed, monkeypatch):
    import app.modules.intake.service as svc

    monkeypatch.setattr(svc, "llm_complete", lambda *a, **k: _ai(
        "PENDING_MANUAL", ""))
    first = intake.submit_intake_message(
        db, principal=_principal(seed), channel="MANUAL", sender="a",
        content="Need a portfolio site")
    db.commit()
    monkeypatch.setattr(svc, "llm_complete", lambda *a, **k: _ai(
        "SUCCEEDED", _CLASSIFIED))
    monkeypatch.setattr(svc, "_EXTRACT_PROMPT", "{content}")
    second = intake.reprocess_intake_message(
        db, principal=_principal(seed), message_id=first.id)
    db.commit()
    assert second.id != first.id and second.status == "CONVERTED"
    assert db.scalar(select(IntakeMessage).where(
        IntakeMessage.id == first.id)).status == "NEEDS_REVIEW"
