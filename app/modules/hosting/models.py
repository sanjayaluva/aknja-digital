"""Hosting and release models: environments, artifacts, approvals, deployments."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import EnvironmentType, ReleaseState
from app.modules.identity.models import TimestampMixin


class ExecutionEnvironment(Base, TimestampMixin):
    __tablename__ = "execution_environments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_execution_environments_tenant_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    env_type: Mapped[str] = mapped_column(String(32), nullable=False)  # EnvironmentType
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    compose_project: Mapped[str] = mapped_column(Text, nullable=False, default="")
    hostname: Mapped[str] = mapped_column(Text, nullable=False, default="")
    auth_policy: Mapped[str] = mapped_column(String(32), nullable=False, default="RESTRICTED")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="INACTIVE")
    provisioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_archive: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    @property
    def env_type_enum(self) -> EnvironmentType:
        return EnvironmentType(self.env_type)


class ReleaseArtifact(Base, TimestampMixin):
    """Build-once immutable artifact record (SRS §11)."""

    __tablename__ = "release_artifacts"
    __table_args__ = (UniqueConstraint("tenant_id", "image_digest", name="uq_release_artifacts_digest"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    image_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    sbom_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")
    migration_set: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    config_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    test_evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ReleaseApproval(Base, TimestampMixin):
    """Production promotion approval bound to exact artifact and nonce."""

    __tablename__ = "release_approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("release_artifacts.id"), nullable=False
    )
    environment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    image_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    approved_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    artifact: Mapped[ReleaseArtifact] = relationship()


class Deployment(Base, TimestampMixin):
    """Release state machine instance (release-state-machine.md)."""

    __tablename__ = "deployments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "version", name="uq_deployments_project_version"),
        Index("ix_deployments_tenant_state", "tenant_id", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("release_artifacts.id"), nullable=False
    )
    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_environments.id"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default=ReleaseState.LOCAL.value, nullable=False)
    gate_results: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    blocked_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rollback_plan: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def state_enum(self) -> ReleaseState:
        return ReleaseState(self.state)
