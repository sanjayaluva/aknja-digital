"""Operations models: system settings, email outbox, jobs, incidents, support.

system_settings implements the zero-hardcode mandate (SRS §8.2): business
parameters live here, not in code. Protected governance invariants are NOT
settings — they live in code/env and cannot be weakened from this table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import IncidentSeverity, IncidentStatus, SupportTicketStatus
from app.modules.identity.models import TimestampMixin


class SystemSetting(Base, TimestampMixin):
    """Typed runtime configuration, editable via the admin settings UI."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)  # tab grouping
    value_json: Mapped[dict | list | str | int | bool | float] = mapped_column(
        JSONB, nullable=False
    )
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)  # string|int|float|bool|json|enum
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class EmailOutbox(Base, TimestampMixin):
    """Durable transactional email outbox (send/retry without loss)."""

    __tablename__ = "email_outbox"
    __table_args__ = (Index("ix_email_outbox_status", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    to_email: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    classification: Mapped[str] = mapped_column(String(32), nullable=False, default="INTERNAL")
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id"), nullable=True
    )


class NotificationOutbox(Base, TimestampMixin):
    """Durable admin-notification outbox (docs/39: send/retry without loss).

    First channel: Telegram (founder digest/alert channel, ml|en templates).
    Duplicate prevention: `idempotency_key` is unique, so a business event
    enqueues exactly once; the rendered body carries a short `· ref` footer
    so a provider-side duplicate (possible after an uncertain timeout) is
    identifiable and reconcilable.
    """

    __tablename__ = "notification_outbox"
    __table_args__ = (
        Index("ix_notification_outbox_status", "status", "next_attempt_at"),
        Index("uq_notification_outbox_idem", "idempotency_key", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="telegram")
    recipient: Mapped[str] = mapped_column(Text, nullable=False, default="")
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="ml")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider_message_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    classification: Mapped[str] = mapped_column(String(32), nullable=False, default="INTERNAL")
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id"), nullable=True
    )


class Job(Base, TimestampMixin):
    """Database-backed durable job queue (SRS §8: low concurrency initially)."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_at", "status", "run_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Incident(Base, TimestampMixin):
    __tablename__ = "incidents"
    __table_args__ = (Index("ix_incidents_tenant_status", "tenant_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    severity: Mapped[str] = mapped_column(
        String(16), default=IncidentSeverity.MEDIUM.value, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default=IncidentStatus.OPEN.value, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timeline: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    recovery_actions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    @property
    def severity_enum(self) -> IncidentSeverity:
        return IncidentSeverity(self.severity)


class SupportTicket(Base, TimestampMixin):
    __tablename__ = "support_tickets"
    __table_args__ = (Index("ix_support_tickets_tenant_status", "tenant_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(32), default=SupportTicketStatus.OPEN.value, nullable=False
    )
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="MEDIUM")
    opened_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolution_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def status_enum(self) -> SupportTicketStatus:
        return SupportTicketStatus(self.status)


class BackupRecord(Base, TimestampMixin):
    __tablename__ = "backup_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="DATABASE")
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at_backup: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restore_drilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Offsite copy (docs/22 §5A): remote object key + push timestamp; both
    # NULL until the artifact has been pushed to S3-compatible storage.
    offsite_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    offsite_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
