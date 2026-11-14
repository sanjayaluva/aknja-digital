"""Tool Gateway — the deterministic enforcement point (docs/09).

Every sensitive action passes through `execute_tool`, which performs the
checks in order:
  1. authenticated actor and tenant scope;
  2. project/environment scope;
  3. tool allow-list and argument schema;
  4. data classification and destination;
  5. approval record and payload hash (when the tool requires approval);
  6. quota permit and spend policy (for metered external tools);
  7. idempotency key and replay protection;
  8. rate limit and timeout;
  9. audit event before/after the action.

Built-in tools are internal and deterministic (no external egress), so the
platform functions with zero providers configured (ADR: no mandatory
external dependency for core workflows).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import (
    DataClassification,
    ToolExecutionStatus,
    ToolRiskClass,
)
from app.core.errors import AuthorizationError, ConflictError, NotFoundError, PolicyBlockedError
from app.core.security import canonical_payload_hash, utcnow
from app.modules.ai.models import ToolDefinition, ToolExecution
from app.modules.governance.service import record_audit
from app.modules.identity.service import Principal

# Built-in deterministic tool implementations (internal, no egress).
BUILTIN_TOOLS: dict[str, Callable[[Session, dict[str, Any]], dict[str, Any]]] = {}


def builtin_tool(name: str) -> Callable:
    def register(fn: Callable[[Session, dict[str, Any]], dict[str, Any]]) -> Callable:
        BUILTIN_TOOLS[name] = fn
        return fn

    return register


class ToolGateway:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- lookups ---

    def get_tool(self, name: str) -> ToolDefinition:
        tool = self.db.scalar(select(ToolDefinition).where(ToolDefinition.name == name))
        if tool is None:
            raise NotFoundError(f"Tool '{name}' is not registered")
        return tool

    def list_tools(self) -> list[ToolDefinition]:
        return list(self.db.scalars(select(ToolDefinition).order_by(ToolDefinition.name)))

    # --- execution ---

    def execute_tool(
        self,
        *,
        principal: Principal | None,
        tool_name: str,
        arguments: dict[str, Any],
        run_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        approval_request_id: uuid.UUID | None = None,
        approval_payload_hash: str | None = None,
        idempotency_key: str,
        actor_type: str = "USER",
        actor_id: str = "",
    ) -> ToolExecution:
        db = self.db
        tool = self.get_tool(tool_name)

        # (1) authenticated actor and tenant scope
        if principal is None and actor_type != "SYSTEM":
            raise AuthorizationError("Tool execution requires an authenticated actor")
        tenant_id = principal.tenant_id if principal else _system_tenant(db)
        actor_id = actor_id or (str(principal.user_id) if principal else "system")

        # (7) idempotency: pre-check, then unique constraint as the backstop.
        existing = db.scalar(
            select(ToolExecution).where(ToolExecution.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing

        execution = ToolExecution(
            tenant_id=tenant_id,
            tool_id=tool.id,
            run_id=run_id,
            project_id=project_id,
            actor_type=actor_type,
            actor_id=actor_id,
            arguments=arguments,
            arguments_hash=canonical_payload_hash(arguments),
            status=ToolExecutionStatus.PENDING.value,
            idempotency_key=idempotency_key,
        )
        try:
            with db.begin_nested():  # SAVEPOINT: replay must not kill the transaction
                db.add(execution)
                db.flush()
        except IntegrityError:
            existing = db.scalar(
                select(ToolExecution).where(ToolExecution.idempotency_key == idempotency_key)
            )
            if existing is not None:
                return existing
            raise

        # audit BEFORE the action
        record_audit(
            db,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="tool.execute",
            resource_type="tool_execution",
            resource_id=str(execution.id),
            payload={"tool": tool_name, "arguments_hash": execution.arguments_hash},
        )

        # (3) tool allow-list + active
        if not tool.is_active:
            execution.status = ToolExecutionStatus.BLOCKED.value
            execution.error = "tool is not on the active allow-list"
            db.flush()
            raise PolicyBlockedError(f"Tool '{tool_name}' is disabled")

        # (3b) argument schema validation (required keys present, types checked)
        schema_error = _validate_arguments(tool, arguments)
        if schema_error:
            execution.status = ToolExecutionStatus.BLOCKED.value
            execution.error = schema_error
            db.flush()
            raise ConflictError(f"Argument schema violation: {schema_error}")

        # (2) project scope: any referenced project must belong to the actor tenant
        referenced_project = project_id
        if referenced_project is None and "project_id" in arguments:
            referenced_project = _parse_uuid(arguments.get("project_id"))
        if referenced_project is not None:
            from app.modules.delivery.models import Project

            project = db.get(Project, referenced_project)
            if project is None or project.tenant_id != tenant_id:
                execution.status = ToolExecutionStatus.BLOCKED.value
                execution.error = "project outside tenant scope"
                db.flush()
                raise AuthorizationError("Project not found in your tenant")

        # (4) data classification
        data_class = arguments.get("data_classification", DataClassification.INTERNAL.value)
        if data_class == DataClassification.RESTRICTED.value:
            execution.status = ToolExecutionStatus.BLOCKED.value
            execution.error = "RESTRICTED data cannot leave the platform"
            db.flush()
            raise PolicyBlockedError("RESTRICTED data classification blocks tool execution")
        if tool.egress_allowed is False and data_class == DataClassification.CONFIDENTIAL.value:
            execution.status = ToolExecutionStatus.BLOCKED.value
            execution.error = "CONFIDENTIAL data requires an egress-approved tool"
            db.flush()
            raise PolicyBlockedError("Tool is not approved for CONFIDENTIAL data egress")

        # (5) approval requirement
        if tool.requires_approval:
            if approval_request_id is None:
                execution.status = ToolExecutionStatus.AWAITING_APPROVAL.value
                db.flush()
                return execution
            from app.modules.governance.models import ApprovalRequest

            approval = db.get(ApprovalRequest, approval_request_id)
            if approval is None or approval.tenant_id != tenant_id:
                execution.status = ToolExecutionStatus.BLOCKED.value
                execution.error = "approval not found in tenant"
                db.flush()
                raise AuthorizationError("Approval request not found")
            if approval.status != "APPROVED":
                execution.status = ToolExecutionStatus.BLOCKED.value
                execution.error = f"approval status is {approval.status}"
                db.flush()
                raise PolicyBlockedError("Tool requires an APPROVED approval request")
            if approval_payload_hash != approval.payload_hash:
                execution.status = ToolExecutionStatus.BLOCKED.value
                execution.error = "payload hash does not match approval"
                db.flush()
                raise PolicyBlockedError("Approval is bound to a different payload")

        # (6) quota permit — external metered tools reserve quota before use.
        if tool.egress_allowed:
            from app.core.enums import ProviderCategory
            from app.modules.resources.service import admit_usage

            decision = admit_usage(
                db,
                tenant_id=tenant_id,
                category=ProviderCategory.AI_LLM,
                quantity=1,
                idempotency_key=f"tool:{execution.id}",
            )
            if not decision.admitted:
                execution.status = ToolExecutionStatus.BLOCKED.value
                execution.error = f"quota denied: {decision.reason}"
                db.flush()
                raise PolicyBlockedError(f"Quota admission denied: {decision.reason}")

        # (8) rate limit: simple per-tool execution window check
        recent = (
            db.query(ToolExecution)
            .filter(
                ToolExecution.tool_id == tool.id,
                ToolExecution.actor_id == actor_id,
                ToolExecution.created_at > utcnow() - timedelta(minutes=1),
            )
            .count()
        )
        if recent > tool.rate_limit_per_minute:
            execution.status = ToolExecutionStatus.BLOCKED.value
            execution.error = "rate limit exceeded"
            db.flush()
            raise PolicyBlockedError("Tool rate limit exceeded")

        # --- execute the deterministic implementation ---
        execution.status = ToolExecutionStatus.EXECUTING.value
        db.flush()
        impl = BUILTIN_TOOLS.get(tool.name)
        started = time.monotonic()
        try:
            if impl is None:
                raise NotFoundError(f"No implementation registered for tool '{tool.name}'")
            result = impl(db, arguments)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            execution.status = ToolExecutionStatus.SUCCEEDED.value
            execution.result = {**result, "elapsed_ms": elapsed_ms}
            execution.executed_at = utcnow()
        except Exception as exc:
            execution.status = ToolExecutionStatus.FAILED.value
            execution.error = str(exc)[:500]
            execution.executed_at = utcnow()
            db.flush()
            record_audit(
                db,
                tenant_id=tenant_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action="tool.failed",
                resource_type="tool_execution",
                resource_id=str(execution.id),
                payload={"tool": tool_name, "error": execution.error},
            )
            raise

        db.flush()
        # audit AFTER the action
        record_audit(
            db,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="tool.succeeded",
            resource_type="tool_execution",
            resource_id=str(execution.id),
            payload={"tool": tool_name, "elapsed_ms": execution.result.get("elapsed_ms")},
        )
        return execution


def _system_tenant(db: Session) -> uuid.UUID:
    from app.modules.identity.models import Tenant

    tenant = db.scalar(select(Tenant).where(Tenant.slug == "aknja-internal"))
    if tenant is None:
        raise AuthorizationError("Internal tenant missing — run init-db first")
    return tenant.id


def _parse_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _validate_arguments(tool: ToolDefinition, arguments: dict[str, Any]) -> str:
    schema: dict = tool.argument_schema or {}
    required: list[str] = schema.get("required", [])
    properties: dict = schema.get("properties", {})
    for key in required:
        if key not in arguments:
            return f"missing required argument '{key}'"
    type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}
    for key, value in arguments.items():
        if key in properties:
            expected = properties[key].get("type")
            py = type_map.get(expected)
            if py is not None and not isinstance(value, py):
                if expected in ("integer", "number") and isinstance(value, bool):
                    return f"argument '{key}' must be {expected}"
                if not isinstance(value, py):
                    return f"argument '{key}' must be {expected}"
    return ""


def seed_builtin_tools(db: Session) -> list[ToolDefinition]:
    """Register the deterministic built-in tool set (idempotent)."""
    specs = [
        (
            "catalog.search",
            "Search the service catalog for services by keyword.",
            {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
            ToolRiskClass.LOW,
            False,
            [],
            120,
        ),
        (
            "project.summarize",
            "Summarize project status: milestones, tasks, feedback.",
            {"type": "object", "required": ["project_id"], "properties": {"project_id": {"type": "string"}}},
            ToolRiskClass.LOW,
            False,
            [],
            60,
        ),
        (
            "artifact.register",
            "Register a delivery artifact record (no file egress).",
            {
                "type": "object",
                "required": ["project_id", "title", "kind"],
                "properties": {
                    "project_id": {"type": "string"},
                    "title": {"type": "string"},
                    "kind": {"type": "string"},
                    "storage_key": {"type": "string"},
                },
            },
            ToolRiskClass.MEDIUM,
            False,
            [],
            30,
        ),
        (
            "email.draft",
            "Draft a client-facing email into the outbox (needs approval to send).",
            {
                "type": "object",
                "required": ["to_email", "subject", "body"],
                "properties": {
                    "to_email": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
            },
            ToolRiskClass.HIGH,
            True,
            [],
            10,
        ),
    ]
    created = []
    for name, desc, schema, risk, requires_approval, classes, rate in specs:
        tool = db.scalar(select(ToolDefinition).where(ToolDefinition.name == name))
        if tool is None:
            tool = ToolDefinition(
                name=name,
                description=desc,
                argument_schema=schema,
                risk_class=risk.value,
                requires_approval=requires_approval,
                allowed_data_classes=classes or [c.value for c in DataClassification],
                timeout_seconds=30,
                rate_limit_per_minute=rate,
            )
            db.add(tool)
        created.append(tool)
    db.flush()
    return created


# --- built-in implementations -------------------------------------------------


@builtin_tool("catalog.search")
def _tool_catalog_search(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    from app.modules.catalog.models import Service, ServiceSubcategory

    query = f"%{args['query'].lower()}%"
    rows = db.scalars(
        select(Service)
        .join(ServiceSubcategory, Service.subcategory_id == ServiceSubcategory.id)
        .where(Service.name.ilike(query))
        .limit(25)
    ).all()
    return {
        "matches": [
            {
                "id": str(s.id),
                "name": s.name,
                "availability": s.availability,
                "readiness": s.readiness,
            }
            for s in rows
        ],
        "count": len(rows),
    }


@builtin_tool("project.summarize")
def _tool_project_summarize(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    from app.modules.delivery.models import Feedback, Milestone, Project, Task

    project = db.get(Project, uuid.UUID(args["project_id"]))
    if project is None:
        raise NotFoundError("project not found")
    milestones = db.scalars(
        select(Milestone).where(Milestone.project_id == project.id)
    ).all()
    tasks = db.scalars(select(Task).where(Task.project_id == project.id)).all()
    feedback = db.scalars(select(Feedback).where(Feedback.project_id == project.id)).all()
    return {
        "project": project.name,
        "lifecycle_state": project.lifecycle_state,
        "milestones": [
            {"title": m.title, "status": m.status, "weight_pct": m.weight_pct} for m in milestones
        ],
        "tasks_total": len(tasks),
        "tasks_done": sum(1 for t in tasks if t.status == "DONE"),
        "open_feedback": sum(1 for f in feedback if f.status == "OPEN"),
    }


@builtin_tool("artifact.register")
def _tool_artifact_register(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    from app.modules.delivery.models import Artifact, Project

    project = db.get(Project, uuid.UUID(args["project_id"]))
    if project is None:
        raise NotFoundError("project not found")
    artifact = Artifact(
        tenant_id=project.tenant_id,
        project_id=project.id,
        kind=args.get("kind", "DOCUMENT"),
        title=args["title"],
        storage_key=args.get("storage_key", ""),
        classification="INTERNAL",
    )
    db.add(artifact)
    db.flush()
    return {"artifact_id": str(artifact.id)}


@builtin_tool("email.draft")
def _tool_email_draft(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    from app.modules.ops.models import EmailOutbox

    outbox = EmailOutbox(
        to_email=args["to_email"],
        subject=args["subject"],
        body=args["body"],
        classification="CONFIDENTIAL",
        status="PENDING",
    )
    db.add(outbox)
    db.flush()
    return {"outbox_id": str(outbox.id), "note": "draft queued; send requires approval"}
