"""Intake pipeline: raw message -> AI classification -> requirements
extraction -> Lead + admin notification (docs/34 §2.3, brief §1.4/§2/§3).

Fail-closed by design: when no governed AI provider is available the record
stops at NEEDS_REVIEW with the reason stored — no phantom leads, no silent
drops, and nothing customer-facing happens without the admin.

One pipeline, every entry path: the admin form, the email poller (T-028)
and the Telegram webhook (T-029) all persist an IntakeMessage first, then
call `process_record` — identical verdicts and audit trails everywhere.
"""

from __future__ import annotations

import json
import re
import uuid

from sqlalchemy.orm import Session

from app.modules.ai.inference import llm_complete
from app.modules.governance.service import record_audit
from app.modules.identity.service import Principal

from .models import CHANNELS, IntakeMessage

_CLASSIFY_PROMPT = """You are the intake classifier for a software engineering
and digital-marketing service provider. Analyze the inbound message below and
output ONLY a JSON object with these fields:
{{"is_project_inquiry": true|false,
  "service_domain": "SOFTWARE_ENGINEERING"|"DIGITAL_MARKETING"|"BOTH"|"OTHER",
  "language": "ml"|"en"|"mixed",
  "urgency": "low"|"normal"|"high",
  "summary": "one-sentence summary of what the sender wants"}}

Inbound message from {sender} via {channel}:

{content}"""

_EXTRACT_PROMPT = """Extract the project requirements from this customer
message. Output ONLY a JSON object:
{{"requirements": ["short requirement bullets, ..."],
  "missing_info": ["important details the sender did NOT specify, ..."],
  "suggested_title": "5-8 word project title"}}

Customer message:

{content}"""


def _parse_json(text: str) -> dict | None:
    """Tolerant JSON extraction (models sometimes wrap in code fences)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _looks_like_email(sender: str) -> str:
    return sender if re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+$", sender or "") else ""


def submit_intake_message(
    db: Session,
    *,
    principal: Principal,
    channel: str,
    sender: str,
    content: str,
    external_id: str | None = None,
) -> IntakeMessage:
    """Persist one inbound message, then run the governed pipeline on it."""
    channel = channel.upper()
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {CHANNELS}")
    content = (content or "").strip()
    if not content:
        raise ValueError("content is required")

    msg = IntakeMessage(
        tenant_id=principal.tenant_id,
        channel=channel,
        sender=(sender or "").strip() or "unknown",
        raw_content=content,
        status="RECEIVED",
        created_by=principal.user_id if channel == "MANUAL" else None,
        external_id=external_id,
    )
    db.add(msg)
    db.flush()
    return process_record(db, principal=principal, record=msg)


def process_record(
    db: Session, *, principal: Principal, record: IntakeMessage
) -> IntakeMessage:
    """Classification -> requirements extraction -> lead + notification on an
    already-persisted record. Shared by every entry path (§3 transparency:
    the raw input and both AI outputs land on the record verbatim)."""
    from app.modules.crm import service as crm
    from app.modules.ops.notifications import notify_admin

    channel = record.channel
    content = record.raw_content

    # 1) classification — is this a project inquiry at all?
    cls = llm_complete(
        db, tenant_id=principal.tenant_id, task="classification",
        prompt=_CLASSIFY_PROMPT.format(sender=record.sender, channel=channel,
                                       content=content[:6000]),
    )
    classification: dict = {"status": cls.status, "provider": cls.provider,
                            "raw_response": (cls.text or "")[:4000]}
    if cls.status != "SUCCEEDED":
        record.status = "NEEDS_REVIEW"
        record.ai_classification = classification
        record.notes = f"classification unavailable: {cls.reason}"
        db.flush()
        record_audit(
            db, tenant_id=principal.tenant_id, actor_type="SYSTEM",
            actor_id="intake", action="intake.needs_review",
            resource_type="intake_message", resource_id=str(record.id),
            payload={"channel": channel, "reason": cls.reason},
        )
        return record
    parsed = _parse_json(cls.text or "")
    if parsed is None:
        record.status = "NEEDS_REVIEW"
        classification["parse_error"] = True
        record.ai_classification = classification
        record.notes = "classification output was not valid JSON"
        db.flush()
        return record
    classification.update(parsed)
    record.ai_classification = classification
    db.flush()

    if not parsed.get("is_project_inquiry"):
        record.status = "REJECTED"  # classified: not a project inquiry
        db.flush()
        record_audit(
            db, tenant_id=principal.tenant_id, actor_type="SYSTEM",
            actor_id="intake", action="intake.rejected",
            resource_type="intake_message", resource_id=str(record.id),
            payload={"channel": channel, "summary": parsed.get("summary", "")},
        )
        return record

    # 2) requirements extraction for real inquiries
    record.status = "CLASSIFIED"
    ext = llm_complete(
        db, tenant_id=principal.tenant_id, task="requirements",
        prompt=_EXTRACT_PROMPT.format(content=content[:6000]),
    )
    extraction: dict = {"status": ext.status, "provider": ext.provider,
                        "raw_response": (ext.text or "")[:6000]}
    if ext.status == "SUCCEEDED":
        parsed_ext = _parse_json(ext.text or "")
        if parsed_ext:
            extraction.update(parsed_ext)
        else:
            extraction["parse_error"] = True
    record.ai_extraction = extraction
    db.flush()

    # 3) lead + admin notification — the workflow entry point
    title = (extraction.get("suggested_title")
             or f"Inquiry from {record.sender} ({channel})")
    description = (
        f"Intake ({channel}) from {record.sender}. AI summary: "
        f"{classification.get('summary', '')}\n\nRequirements:\n"
        + "\n".join(f"- {r}" for r in extraction.get("requirements", [])[:12])
        + ("\n\nMissing information:\n" + "\n".join(
            f"- {m}" for m in extraction.get("missing_info", [])[:8])
           if extraction.get("missing_info") else "")
        + f"\n\nSource record: intake_messages/{record.id}"
    )
    lead = crm.create_lead(
        db, principal=principal, title=title[:200], source=channel,
        description=description[:5000],
        contact_email=_looks_like_email(record.sender),
    )
    record.lead_id = lead.id
    record.status = "CONVERTED"
    db.flush()
    notify_admin(
        db,
        template_key="intake.received",
        payload={"channel": channel, "sender": record.sender,
                 "summary": classification.get("summary", "")[:120],
                 "lead_title": lead.title},
        idempotency_key=f"intake:{record.id}",
        tenant_id=principal.tenant_id,
    )
    record_audit(
        db, tenant_id=principal.tenant_id, actor_type="SYSTEM",
        actor_id="intake", action="intake.converted",
        resource_type="intake_message", resource_id=str(record.id),
        payload={"channel": channel, "lead_id": str(lead.id),
                 "domain": classification.get("service_domain", "")},
    )
    return record


def reprocess_intake_message(
    db: Session, *, principal: Principal, message_id: uuid.UUID
) -> IntakeMessage:
    """Re-run the AI pipeline on the stored raw input (e.g. after provider
    recovery or a prompt improvement). Keeps the original record; a fresh
    row is written so both verdicts stay auditable."""
    row = db.get(IntakeMessage, message_id)
    if row is None or row.tenant_id != principal.tenant_id:
        from app.core.errors import NotFoundError

        raise NotFoundError("intake message not found")
    return submit_intake_message(
        db, principal=principal, channel=row.channel, sender=row.sender,
        content=row.raw_content,
        external_id=row.external_id,
    )
