"""AI orchestration models: capabilities, runs, tools, memory.

One Central AI Orchestrator coordinates task-scoped specialist capabilities
(.aknja/agents). Workers have no independent credentials; every side effect
goes through the Tool Gateway (docs/09).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import AgentRunState, DataClassification, ToolExecutionStatus, ToolRiskClass
from app.modules.identity.models import TimestampMixin

BigIntFk = BigInteger().with_variant(Integer, "sqlite")


class AgentCapability(Base, TimestampMixin):
    """Task-scoped capability template (.aknja/agents initial registry)."""

    __tablename__ = "agent_capabilities"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_agent_capabilities_tenant_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    allowed_tools: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    allowed_data_classes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    max_budget_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    requires_verification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AgentRun(Base, TimestampMixin):
    """Stateful orchestrator run (ai-execution-state-machine)."""

    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_tenant_state", "tenant_id", "state"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    capability_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_capabilities.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True)
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_environments.id"), nullable=True
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default=AgentRunState.OBSERVE.value, nullable=False)
    plan: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    context_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    acceptance_criteria: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    data_classification: Mapped[str] = mapped_column(
        String(32), default=DataClassification.INTERNAL.value, nullable=False
    )
    budget_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    verification_evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result_artifacts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    unresolved_questions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    policy_version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("policy_versions.id"), nullable=True
    )
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list[AgentRunEvent]] = relationship(
        back_populates="run", order_by="AgentRunEvent.created_at"
    )
    capability: Mapped[AgentCapability] = relationship()

    @property
    def state_enum(self) -> AgentRunState:
        return AgentRunState(self.state)


class AgentRunEvent(Base):
    """Every state transition with actor, timestamp and audit reference."""

    __tablename__ = "agent_run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False
    )
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, default="SYSTEM")
    actor_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    audit_event_id: Mapped[int | None] = mapped_column(BigIntFk, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[AgentRun] = relationship(back_populates="events")


class ToolDefinition(Base, TimestampMixin):
    """Deterministic tool registry — the actual enforcement point."""

    __tablename__ = "tool_definitions"
    __table_args__ = (UniqueConstraint("name", name="uq_tool_definitions_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    argument_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risk_class: Mapped[str] = mapped_column(
        String(16), default=ToolRiskClass.MEDIUM.value, nullable=False
    )
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allowed_data_classes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    egress_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=60)


class ToolExecution(Base, TimestampMixin):
    __tablename__ = "tool_executions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_tool_executions_idempotency"),
        Index("ix_tool_executions_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tool_definitions.id"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, default="USER")
    actor_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    arguments: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=ToolExecutionStatus.PENDING.value, nullable=False
    )
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id"), nullable=True
    )
    quota_reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quota_reservations.id"), nullable=True
    )
    permit_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tool: Mapped[ToolDefinition] = relationship()


class MemoryRecord(Base, TimestampMixin):
    """Reviewed, non-sensitive memory with provenance (.aknja/memory)."""

    __tablename__ = "memory_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="PROJECT")
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="EPISODIC")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sensitivity: Mapped[str] = mapped_column(
        String(32), default=DataClassification.INTERNAL.value, nullable=False
    )
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LLMCallLog(Base, TimestampMixin):
    """Reproducibility record for LLM inference (v5.3.2 §5C).

    Stores provider/model + prompt-template version for every attempt, plus
    a prompt HASH only — raw prompts may contain client content and are
    never persisted here.
    """

    __tablename__ = "llm_call_logs"
    __table_args__ = (Index("ix_llm_call_logs_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    task: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)  # SUCCEEDED|FAILED|PENDING_MANUAL
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    template_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
