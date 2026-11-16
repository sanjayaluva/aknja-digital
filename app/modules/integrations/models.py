"""Integration credential hub (docs/34, T-027).

Admin-managed, DB-stored, Fernet-encrypted credentials for every external
service (LLM providers, email, messaging, transcription, VCS). Resolution is
DB-first with env fallback so the .env file degrades from "the credential
store" to "disaster-recovery seed" — no source change is ever needed to add
or rotate a key.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.identity.models import TimestampMixin


class IntegrationCredential(Base, TimestampMixin):
    """One credential set per (tenant, provider_key).

    `payload_encrypted` holds a Fernet-encrypted JSON object of secrets
    ({"api_key": "..."} / {"api_keys": "k1,k2"} / {"app_password": "..."}).
    `config` holds NON-secret settings (imap_host, bot_username, model).
    """

    __tablename__ = "integration_credentials"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_key", name="uq_integration_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # LLM | EMAIL | MESSAGING | TRANSCRIPTION | VCS | GENERIC
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_key: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # "gemini", "gmail", "telegram_bot", ...
    # DRAFT (entered, not verified) | ACTIVE | INACTIVE | FAILED (test failed)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    payload_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_tested_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_test_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
