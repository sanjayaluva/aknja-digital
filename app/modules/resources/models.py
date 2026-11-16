"""Resource plane models: providers, quotas, reservations, circuit breakers.

Implements the Zero-Cost Guard (v5.3.1) and category-based provider pools
(v5.3.2). Fail-closed semantics: unknown or stale quota is unavailable.
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import (
    BillingState,
    ProviderCategory,
    QuotaConfidence,
    ReservationStatus,
)
from app.modules.identity.models import TimestampMixin


class ProviderAccount(Base, TimestampMixin):
    """A provider account registration. Secrets are referenced by name only."""

    __tablename__ = "provider_accounts"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "account_ref", name="uq_provider_accounts"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)  # neon, cloudflare_r2, groq...
    account_ref: Mapped[str] = mapped_column(Text, nullable=False, default="default")
    display_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    plan: Mapped[str] = mapped_column(String(64), nullable=False, default="FREE")
    billing_state: Mapped[str] = mapped_column(
        String(32), default=BillingState.FREE_UNVERIFIED.value, nullable=False
    )
    region: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    secret_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")  # env var name only
    data_policy_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    commercial_use_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    health: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")
    quality_benchmark: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    products: Mapped[list[ProviderProduct]] = relationship(back_populates="account")

    @property
    def is_eligible_free(self) -> bool:
        return self.enabled and self.billing_state == BillingState.FREE_VERIFIED.value


class ProviderProduct(Base, TimestampMixin):
    """A metered product/limit within a provider account."""

    __tablename__ = "provider_products"
    __table_args__ = (
        UniqueConstraint("account_id", "product_key", name="uq_provider_products_account_key"),
        Index("ix_provider_products_category", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_accounts.id"), nullable=False
    )
    product_key: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "gemini-2.5-flash tokens/day"
    # admin-editable model id used by llm_complete (docs/34 §2.4): empty =
    # built-in default per provider; set to switch a provider to another
    # model without a code change
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False)  # ProviderCategory
    capability_contract: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False, default="requests")
    allowance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="count")
    reset_period: Mapped[str] = mapped_column(String(16), nullable=False, default="DAILY")
    metric_source: Mapped[str] = mapped_column(String(32), nullable=False, default="LOCAL")
    metrics_delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    account: Mapped[ProviderAccount] = relationship(back_populates="products")
    snapshots: Mapped[list[QuotaSnapshot]] = relationship(
        back_populates="product", order_by="QuotaSnapshot.observed_at.desc()"
    )
    reservations: Mapped[list[QuotaReservation]] = relationship(back_populates="product")

    @property
    def category_enum(self) -> ProviderCategory:
        return ProviderCategory(self.category)


class QuotaSnapshot(Base):
    """Point-in-time usage observation (provider-reported or locally metered)."""

    __tablename__ = "quota_snapshots"
    __table_args__ = (
        Index("ix_quota_snapshots_product_observed", "provider_product_id", "observed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_products.id"), nullable=False
    )
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False)
    allowance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_reported_usage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locally_metered_usage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_usage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[str] = mapped_column(
        String(16), default=QuotaConfidence.MEDIUM.value, nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped[ProviderProduct] = relationship(back_populates="snapshots")


class QuotaReservation(Base):
    """Atomic usage reservation with safety reserve (docs/13 algorithm)."""

    __tablename__ = "quota_reservations"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_quota_reservations_idempotency"),
        Index("ix_quota_reservations_product_status", "provider_product_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_products.id"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=ReservationStatus.RESERVED.value, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    actual_usage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped[ProviderProduct] = relationship(back_populates="reservations")


class UsageEvent(Base):
    """Local metering ledger (authoritative when provider metrics are delayed)."""

    __tablename__ = "usage_events"
    __table_args__ = (Index("ix_usage_events_product_created", "provider_product_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_products.id"), nullable=False
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quota_reservations.id"), nullable=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="count")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="LOCAL")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CircuitBreaker(Base):
    """Per-product circuit breaker tripped on 429/402/5xx, with cooldown."""

    __tablename__ = "circuit_breakers"
    __table_args__ = (
        UniqueConstraint("provider_product_id", name="uq_circuit_breakers_product"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_products.id"), nullable=False, unique=True
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="CLOSED")  # CLOSED|OPEN|HALF_OPEN
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_failure_code: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    tripped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProviderPool(Base, TimestampMixin):
    """Category-based pool of equivalent free providers (v5.3.2)."""

    __tablename__ = "provider_pools"
    __table_args__ = (UniqueConstraint("tenant_id", "category", name="uq_provider_pools_tenant_category"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    min_quality_threshold: Mapped[Numeric] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    failover_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ProviderQualityBenchmark(Base, TimestampMixin):
    """Latest-vs-history quality benchmark record (v5.3.2 §7).

    One row per benchmark run: which provider product, which tasks and
    languages, the per-task scores against the floors, and the pass verdict.
    The inference gate (`benchmark_gate`) reads the newest fresh row to keep
    floor-failing providers out of the pool for the tasks they failed.
    """

    __tablename__ = "provider_quality_benchmarks"
    __table_args__ = (
        Index("ix_pqb_product_evaluated", "provider_product_id", "evaluated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_products.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    benchmark_version: Mapped[str] = mapped_column(String(16), nullable=False)
    tasks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    languages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    score_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
