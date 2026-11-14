"""Central model registry — importing this module registers every model on
the shared metadata so Alembic autogenerate and `Base.metadata.create_all`
see the full schema."""

from __future__ import annotations

from app.modules.ai.models import (
    AgentCapability,
    AgentRun,
    AgentRunEvent,
    MemoryRecord,
    ToolDefinition,
    ToolExecution,
)
from app.modules.catalog.models import (
    PricingPackage,
    Service,
    ServiceBlueprint,
    ServiceCategory,
    ServiceReadinessEvidence,
    ServiceSubcategory,
)
from app.modules.commercial.models import (
    ChangeRequest,
    Contract,
    Invoice,
    Payment,
    Proposal,
)
from app.modules.crm.models import Client, Contact, Lead
from app.modules.delivery.models import (
    Artifact,
    Feedback,
    Milestone,
    Project,
    Requirement,
    StagingPreview,
    Task,
    TaskDependency,
    UATAcceptance,
)
from app.modules.governance.models import (
    ApprovalDecision,
    ApprovalRequest,
    EmergencyStop,
    PolicyVersion,
)
from app.modules.hosting.models import (
    Deployment,
    ExecutionEnvironment,
    ReleaseApproval,
    ReleaseArtifact,
)
from app.modules.identity.models import Tenant, TenantMembership, User, UserSession
from app.modules.ops.models import (
    BackupRecord,
    EmailOutbox,
    Incident,
    Job,
    SupportTicket,
    SystemSetting,
)
from app.modules.resources.models import (
    CircuitBreaker,
    ProviderAccount,
    ProviderPool,
    ProviderProduct,
    QuotaReservation,
    QuotaSnapshot,
    UsageEvent,
)

__all__ = [
    "AgentCapability",
    "AgentRun",
    "AgentRunEvent",
    "ApprovalDecision",
    "ApprovalRequest",
    "Artifact",
    "BackupRecord",
    "ChangeRequest",
    "CircuitBreaker",
    "Client",
    "Contact",
    "Contract",
    "Deployment",
    "EmailOutbox",
    "EmergencyStop",
    "ExecutionEnvironment",
    "Feedback",
    "Incident",
    "Invoice",
    "Job",
    "Lead",
    "MemoryRecord",
    "Milestone",
    "Payment",
    "PolicyVersion",
    "PricingPackage",
    "Project",
    "Proposal",
    "ProviderAccount",
    "ProviderPool",
    "ProviderProduct",
    "QuotaReservation",
    "QuotaSnapshot",
    "ReleaseApproval",
    "ReleaseArtifact",
    "Requirement",
    "Service",
    "ServiceBlueprint",
    "ServiceCategory",
    "ServiceReadinessEvidence",
    "ServiceSubcategory",
    "StagingPreview",
    "SupportTicket",
    "SystemSetting",
    "Task",
    "TaskDependency",
    "Tenant",
    "TenantMembership",
    "ToolDefinition",
    "ToolExecution",
    "UATAcceptance",
    "UsageEvent",
    "User",
    "UserSession",
]
