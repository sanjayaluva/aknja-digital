"""Intake pipeline: raw message -> AI classification -> requirements
extraction -> Lead + admin notification (docs/34 §2.3, brief §1.4/§2/§3).

Fail-closed by design: when no governed AI provider is available the record
stops at NEEDS_REVIEW with the reason stored — no phantom leads, no silent
drops, and nothing customer-facing happens without the admin.
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
) -> IntakeMessage:
    """One inbound message through the full governed pipeline."""
    from app.modules.crm import service as crm
    from app.modules.ops.notifications import notify_admin

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
    )
    db.add(msg)
    db.flush()

    # 1) classification — is this a project inquiry at all?
    cls = llm_complete(
        db, tenant_id=principal.tenant_id, task="classification",
        prompt=_CLASSIFY_PROMPT.format(sender=msg.sender, channel=channel,
                                       content=content[:6000]),
    )
    classification: dict = {"status": cls.status, "provider": cls.provider,
                            "raw_response": (cls.text or "")[:4000]}
    if cls.status != "SUCCEEDED":
        msg.status = "NEEDS_REVIEW"
        msg.ai_classification = classification
        msg.notes = f"classification unavailable: {cls.reason}"
        db.flush()
        record_audit(
            db, tenant_id=principal.tenant_id, actor_type="SYSTEM",
            actor_id="intake", action="intake.needs_review",
            resource_type="intake_message", resource_id=str(msg.id),
            payload={"channel": channel, "reason": cls.reason},
        )
        return msg
    parsed = _parse_json(cls.text or "")
    if parsed is None:
        msg.status = "NEEDS_REVIEW"
        classification["parse_error"] = True
        msg.ai_classification = classification
        msg.notes = "classification output was not valid JSON"
        db.flush()
        return msg
    classification.update(parsed)
    msg.ai_classification = classification
    db.flush()

    if not parsed.get("is_project_inquiry"):
        msg.status = "REJECTED"  # classified: not a project inquiry
        db.flush()
        record_audit(
            db, tenant_id=principal.tenant_id, actor_type="SYSTEM",
            actor_id="intake", action="intake.rejected",
            resource_type="intake_message", resource_id=str(msg.id),
            payload={"channel": channel, "summary": parsed.get("summary", "")},
        )
        return msg

    # 2) requirements extraction for real inquiries
    msg.status = "CLASSIFIED"
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
    msg.ai_extraction = extraction
    db.flush()

    # 3) lead + admin notification — the workflow entry point
    title = (extraction.get("suggested_title")
             or f"Inquiry from {msg.sender} ({channel})")
    description = (
        f"Intake ({channel}) from {msg.sender}. AI summary: "
        f"{classification.get('summary', '')}\n\nRequirements:\n"
        + "\n".join(f"- {r}" for r in extraction.get("requirements", [])[:12])
        + ("\n\nMissing information:\n" + "\n".join(
            f"- {m}" for m in extraction.get("missing_info", [])[:8])
           if extraction.get("missing_info") else "")
        + f"\n\nSource record: intake_messages/{msg.id}"
    )
    lead = crm.create_lead(
        db, principal=principal, title=title[:200], source=channel,
        description=description[:5000],
        contact_email=_looks_like_email(msg.sender),
    )
    msg.lead_id = lead.id
    msg.status = "CONVERTED"
    db.flush()
    notify_admin(
        db,
        template_key="intake.received",
        payload={"channel": channel, "sender": msg.sender,
                 "summary": classification.get("summary", "")[:120],
                 "lead_title": lead.title},
        idempotency_key=f"intake:{msg.id}",
        tenant_id=principal.tenant_id,
    )
    record_audit(
        db, tenant_id=principal.tenant_id, actor_type="SYSTEM",
        actor_id="intake", action="intake.converted",
        resource_type="intake_message", resource_id=str(msg.id),
        payload={"channel": channel, "lead_id": str(lead.id),
                 "domain": classification.get("service_domain", "")},
    )
    return msg


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
    )
