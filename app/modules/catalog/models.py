"""Service catalog models (docs/07 + preserved source taxonomy).

Hierarchy: Category → Subcategory → Service (leaf) → Blueprint.
`Service` rows are leaf entries from the source taxonomy. Availability
(truthful sellability) and readiness (execution capability) are tracked
independently and default to CATALOG_ONLY / PLANNED.
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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import ExecutionMode, ServiceAvailability, ServiceReadiness
from app.modules.identity.models import TimestampMixin


class ServiceCategory(Base, TimestampMixin):
    __tablename__ = "service_categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "domain", "code", name="uq_service_categories_tenant_domain_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(32), nullable=False)  # SOFTWARE_ENGINEERING | DIGITAL_MARKETING
    code: Mapped[str] = mapped_column(String(16), nullable=False)  # "1.0", "2.0", ...
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    subcategories: Mapped[list[ServiceSubcategory]] = relationship(
        back_populates="category", order_by="ServiceSubcategory.sort_order"
    )


class ServiceSubcategory(Base, TimestampMixin):
    __tablename__ = "service_subcategories"
    __table_args__ = (
        UniqueConstraint("category_id", "code", name="uq_service_subcategories_category_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_categories.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)  # "1.1", "1.2", ...
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    category: Mapped[ServiceCategory] = relationship(back_populates="subcategories")
    services: Mapped[list[Service]] = relationship(
        back_populates="subcategory", order_by="Service.sort_order"
    )


class Service(Base, TimestampMixin):
    __tablename__ = "services"
    __table_args__ = (
        UniqueConstraint("subcategory_id", "name", name="uq_services_subcategory_name"),
        Index("ix_services_tenant_readiness", "tenant_id", "readiness"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    subcategory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_subcategories.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    availability: Mapped[str] = mapped_column(
        String(32), default=ServiceAvailability.CATALOG_ONLY.value, nullable=False
    )
    readiness: Mapped[str] = mapped_column(
        String(32), default=ServiceReadiness.PLANNED.value, nullable=False
    )
    execution_mode: Mapped[str] = mapped_column(
        String(48), default=ExecutionMode.MANUAL.value, nullable=False
    )
    data_classification: Mapped[str] = mapped_column(String(32), nullable=False, default="INTERNAL")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sellable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    subcategory: Mapped[ServiceSubcategory] = relationship(back_populates="services")
    blueprints: Mapped[list[ServiceBlueprint]] = relationship(back_populates="service")

    @property
    def is_sellable_now(self) -> bool:
        """A service can be quoted only with truthful availability+readiness (SRS §3)."""
        return (
            self.sellable
            and self.availability in (
                ServiceAvailability.AVAILABLE_MANUAL.value,
                ServiceAvailability.AVAILABLE_WITH_PARTNER.value,
                ServiceAvailability.AVAILABLE_AI_ASSISTED.value,
                ServiceAvailability.AVAILABLE_AUTOMATED.value,
            )
            and self.readiness in (ServiceReadiness.LIMITED.value, ServiceReadiness.READY.value)
        )


class ServiceBlueprint(Base, TimestampMixin):
    """Scoped execution contract for one service (docs/07 blueprint stages)."""

    __tablename__ = "service_blueprints"
    __table_args__ = (
        UniqueConstraint("service_id", "version", name="uq_service_blueprints_service_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="")
    exclusions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    intake_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    prerequisites: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    capability_requirements: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tool_requirements: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    workflow: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    qa_checklist: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    acceptance_criteria: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    deliverable_contract: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    approval_requirements: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    estimated_effort_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    service: Mapped[Service] = relationship(back_populates="blueprints")


class PricingPackage(Base, TimestampMixin):
    __tablename__ = "pricing_packages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    billing_period: Mapped[str] = mapped_column(String(32), nullable=False, default="ONE_TIME")
    includes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    excludes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ServiceReadinessEvidence(Base, TimestampMixin):
    __tablename__ = "service_readiness_evidence"
    __table_args__ = (
        UniqueConstraint("service_id", "evidence_key", name="uq_readiness_evidence_service_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id"), nullable=False
    )
    evidence_key: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    artifact_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")
