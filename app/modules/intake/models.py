"""Unified multi-channel intake (docs/34, T-027).

Every inbound message — manual text now; email / Telegram / WhatsApp /
voice in later phases — lands in one table with the raw input, the channel,
both AI outputs (classification + requirements extraction) verbatim, and
the lead it produced. That record IS the §3 transparency guarantee: the
admin can inspect exactly what came in and what the AI made of it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.identity.models import TimestampMixin

CHANNELS = ("MANUAL", "EMAIL", "TELEGRAM", "WHATSAPP", "VOICE", "PHONE")
STATUSES = ("RECEIVED", "CLASSIFIED", "CONVERTED", "NEEDS_REVIEW", "REJECTED")


class IntakeMessage(Base, TimestampMixin):
    __tablename__ = "intake_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)  # CHANNELS
    sender: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    # RECEIVED -> CLASSIFIED -> CONVERTED | NEEDS_REVIEW | REJECTED
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RECEIVED")
    # verbatim AI outputs: {"is_project_inquiry":..., "summary":..., "raw_response":...}
    ai_classification: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ai_extraction: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
