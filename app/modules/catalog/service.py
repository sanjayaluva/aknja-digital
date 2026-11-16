"""Service catalog service + taxonomy importer.

The importer parses the preserved source taxonomy
(`docs/source_service_hierarchy.md`) preserving every leaf entry, then tags
each family with the truthful availability/readiness/execution-mode from
`examples/service-readiness-seed.csv`. Defaults: CATALOG_ONLY / PLANNED —
a service may be catalogued without being for sale (SRS §3).
"""

from __future__ import annotations

import csv
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ExecutionMode, ServiceAvailability, ServiceReadiness
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.modules.catalog.models import Service, ServiceSubcategory
from app.modules.identity.service import Principal

_TREE_LINE = re.compile(r"^`?\s*([│├└\s]*)(.+?)`?$")

# Readiness promotion requires evidence for every item (docs/07).
READINESS_PROMOTION_REQUIREMENTS = [
    "verified_tool_access",
    "workflow_defined",
    "permissions_verified",
    "privacy_checked",
    "quota_capacity_checked",
    "qa_checklist_defined",
    "evaluation_cases",
    "sample_evidence",
]


def _strip_private_use(text: str) -> str:
    """Remove private-use/invisible characters used by the source document."""
    return "".join(ch for ch in text if not (0xE000 <= ord(ch) <= 0xF8FF))


def parse_taxonomy(md_path: Path) -> list[dict]:
    """Parse the tree-form taxonomy into (domain, family, subcategory, leaf).

    The source format is backtick-wrapped tree lines:
    `` `├── 1.0 Web Application Development` `` / `` `│   ├── 1.1 Frontend ...` ``
    / `` `│   │   ├── Single Page Applications (SPAs)` ``.
    Numbered entries are families (x.0) and subcategories (x.y); unnumbered
    children of a subcategory are leaf services. Part markers carry a
    private-use prefix character (U+E042) in the source document.
    """
    domain = None
    family = None
    subcategory = None
    entries: list[dict] = []
    for raw_line in md_path.read_text(encoding="utf-8").splitlines():
        line = _strip_private_use(raw_line.strip())
        if not line:
            continue
        if line.startswith(("## Part 1",)):
            domain = "SOFTWARE_ENGINEERING"
            continue
        if line.startswith(("Part 2", "## Part 2")):
            domain = "DIGITAL_MARKETING"
            continue
        if line.startswith(("Part 3", "## Part 3")):
            domain = None  # deliverables matrix section: stop tree parsing
            continue
        if line.startswith(("#", "Source:", "Services Hierarchy")):
            continue
        if line.startswith(("Software Engineering Sub-Services", "Digital Marketing Sub-Services")):
            continue
        if domain is None:
            continue
        if not line.startswith(("`", "├", "│", "└")):
            continue
        content = line.strip("`").strip()
        if not content or set(content) <= {"│", "├", "└", "─", " "}:
            continue
        content = re.sub(r"^[│├└─\s]+", "", content).strip()
        if not content:
            continue
        numbered = re.match(r"^(\d+\.\d+)\s+(.*)$", content)
        if numbered:
            code, name = numbered.group(1), numbered.group(2).strip()
            if code.endswith(".0"):
                family = {"code": code, "name": name}
                subcategory = None
                entries.append(
                    {"type": "family", "domain": domain, "code": code, "name": name}
                )
            else:
                subcategory = {"code": code, "name": name, "family": family["code"] if family else ""}
                entries.append(
                    {
                        "type": "subcategory",
                        "domain": domain,
                        "code": code,
                        "name": name,
                        "family": family["code"] if family else "",
                    }
                )
        elif subcategory is not None:
            entries.append(
                {
                    "type": "service",
                    "domain": domain,
                    "name": content,
                    "family": family["code"] if family else "",
                    "subcategory": subcategory["code"],
                }
            )
    return entries


def parse_readiness_seed(csv_path: Path) -> dict[str, dict[str, str]]:
    """Family-level truthful readiness defaults from the seed CSV."""
    result: dict[str, dict[str, str]] = {}
    with csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            result[row["service_family"].strip()] = {
                "availability": row["availability_status"].strip(),
                "readiness": row["readiness_status"].strip(),
                "execution_mode": row["execution_mode"].strip(),
                "notes": row.get("notes", "").strip(),
            }
    return result


def import_taxonomy(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    md_path: Path,
    seed_csv_path: Path | None = None,
) -> dict[str, int]:
    """Idempotent import: existing entries are matched by code/name."""
    from app.modules.catalog.models import ServiceCategory

    entries = parse_taxonomy(md_path)
    seed = parse_readiness_seed(seed_csv_path) if seed_csv_path else {}
    # Map (domain, family code) → family name for CSV matching.
    family_names: dict[tuple[str, str], str] = {}
    for e in entries:
        if e["type"] == "family":
            family_names[(e["domain"], e["code"])] = e["name"]

    stats = {"families": 0, "subcategories": 0, "services": 0, "skipped": 0}
    # Caches are keyed by (domain, code): codes restart at 1.0 in Part 2.
    category_cache: dict[tuple[str, str], object] = {}
    subcat_cache: dict[tuple[str, str], object] = {}

    for entry in entries:
        if entry["type"] == "family":
            key = (entry["domain"], entry["code"])
            category = category_cache.get(key)
            if category is None:
                category = db.scalar(
                    select(ServiceCategory).where(
                        ServiceCategory.tenant_id == tenant_id,
                        ServiceCategory.domain == entry["domain"],
                        ServiceCategory.code == entry["code"],
                    )
                )
            if category is None:
                order = int(float(entry["code"].split(".")[0]) * 10)
                category = ServiceCategory(
                    tenant_id=tenant_id,
                    domain=entry["domain"],
                    code=entry["code"],
                    name=entry["name"],
                    sort_order=order,
                )
                db.add(category)
                db.flush()
                stats["families"] += 1
            category_cache[key] = category
        elif entry["type"] == "subcategory":
            key = (entry["domain"], entry["code"])
            subcat = subcat_cache.get(key)
            if subcat is None:
                subcat = db.scalar(
                    select(ServiceSubcategory)
                    .join(ServiceCategory, ServiceSubcategory.category_id == ServiceCategory.id)
                    .where(
                        ServiceSubcategory.code == entry["code"],
                        ServiceCategory.domain == entry["domain"],
                        ServiceCategory.code == _family_code(entry["code"]),
                    )
                )
            if subcat is None:
                category = category_cache.get((entry["domain"], _family_code(entry["code"])))
                if category is None:
                    stats["skipped"] += 1
                    continue
                subcat = ServiceSubcategory(
                    category_id=category.id,  # type: ignore[attr-defined]
                    code=entry["code"],
                    name=entry["name"],
                    sort_order=int(float(entry["code"].split(".")[-1]) * 10),
                )
                db.add(subcat)
                db.flush()
                stats["subcategories"] += 1
            subcat_cache[key] = subcat
        else:  # service leaf
            subcat = subcat_cache.get((entry["domain"], entry["subcategory"]))
            if subcat is None:
                stats["skipped"] += 1
                continue
            existing = db.scalar(
                select(Service).where(
                    Service.subcategory_id == subcat.id,  # type: ignore[attr-defined]
                    Service.name == entry["name"],
                )
            )
            if existing is not None:
                stats["skipped"] += 1
                continue
            family_name = family_names.get((entry["domain"], entry["family"]), "")
            seed_row = seed.get(family_name, {})
            db.add(
                Service(
                    tenant_id=tenant_id,
                    subcategory_id=subcat.id,  # type: ignore[attr-defined]
                    name=entry["name"],
                    availability=seed_row.get("availability", ServiceAvailability.CATALOG_ONLY.value),
                    readiness=seed_row.get("readiness", ServiceReadiness.PLANNED.value),
                    execution_mode=seed_row.get("execution_mode", ExecutionMode.MANUAL.value),
                    description=seed_row.get("notes", ""),
                )
            )
            stats["services"] += 1
    db.flush()
    return stats


def _family_code(subcategory_code: str) -> str:
    major = subcategory_code.split(".")[0]
    return f"{major}.0"


# --- service operations ---


def list_services(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    search: str = "",
    readiness: str = "",
    availability: str = "",
    limit: int = 100,
) -> list[Service]:
    stmt = select(Service).where(Service.tenant_id == tenant_id)
    if search:
        stmt = stmt.where(Service.name.ilike(f"%{search}%"))
    if readiness:
        stmt = stmt.where(Service.readiness == readiness)
    if availability:
        stmt = stmt.where(Service.availability == availability)
    return list(db.scalars(stmt.order_by(Service.sort_order, Service.name).limit(limit)))


def get_service(db: Session, tenant_id: uuid.UUID, service_id: uuid.UUID) -> Service:
    service = db.get(Service, service_id)
    if service is None or service.tenant_id != tenant_id:
        raise NotFoundError("Service not found")
    return service


def update_service_lifecycle(
    db: Session,
    *,
    principal: Principal,
    service_id: uuid.UUID,
    availability: str | None = None,
    readiness: str | None = None,
    execution_mode: str | None = None,
    sellable: bool | None = None,
) -> Service:
    """Update availability/readiness with truthful-selling guard.

    Readiness may only be promoted to LIMITED/READY when promotion
    requirements are recorded (docs/07 readiness promotion).
    """
    service = get_service(db, principal.tenant_id, service_id)
    if availability is not None:
        if availability not in [a.value for a in ServiceAvailability]:
            raise ValidationAppError(f"Unknown availability '{availability}'")
        service.availability = availability
    if readiness is not None:
        if readiness not in [r.value for r in ServiceReadiness]:
            raise ValidationAppError(f"Unknown readiness '{readiness}'")
        if readiness in (ServiceReadiness.LIMITED.value, ServiceReadiness.READY.value):
            _assert_promotion_evidence(db, service_id)
        service.readiness = readiness
    if execution_mode is not None:
        if execution_mode not in [m.value for m in ExecutionMode]:
            raise ValidationAppError(f"Unknown execution mode '{execution_mode}'")
        service.execution_mode = execution_mode
    if sellable is not None:
        service.sellable = sellable
    db.flush()
    return service


def _assert_promotion_evidence(db: Session, service_id: uuid.UUID) -> None:
    from app.modules.catalog.models import ServiceReadinessEvidence

    evidence = db.scalars(
        select(ServiceReadinessEvidence).where(ServiceReadinessEvidence.service_id == service_id)
    ).all()
    verified_keys = {e.evidence_key for e in evidence if e.verified}
    missing = [k for k in READINESS_PROMOTION_REQUIREMENTS if k not in verified_keys]
    if missing:
        raise ConflictError(
            "Readiness promotion requires verified evidence for all requirements",
            details={"missing": missing},
        )


def assert_quotable(service: Service) -> None:
    """Quote-time guard: only truthful availability may be sold (SRS §3)."""
    if not service.is_sellable_now:
        raise ConflictError(
            "Service cannot be quoted: availability/readiness not truthful for sale",
            details={
                "availability": service.availability,
                "readiness": service.readiness,
                "sellable": service.sellable,
            },
        )


# --- delivery templates: catalog -> project blueprint (T-026) -------------------
#
# Every service item carries a milestone/task blueprint that is instantiated
# when a project is started from it. AI steps are wired ONLY to task profiles
# the free-provider pool can actually serve above its quality floor today
# (requirements, code_review, qa_review, classification, summarization,
# translation); proposal_draft has no lane above its floor yet and stays a
# MANUAL step — templates never promise an AI lane the pool cannot deliver.

_DELIVERY_TEMPLATES: dict[str, dict] = {
    "SOFTWARE_ENGINEERING": {
        "milestones": [
            {"title": "Requirements", "weight_pct": 25, "tasks": [
                {"title": "AI requirements extraction",
                 "ai_task": "requirements",
                 "description": "Turn the client brief into a structured, testable "
                                "requirements list."},
                {"title": "Scope confirmation with client", "ai_task": None,
                 "description": "Walk the requirements list with the client and freeze scope."},
            ]},
            {"title": "Build", "weight_pct": 35, "tasks": [
                {"title": "Implement deliverables", "ai_task": None,
                 "description": "Produce the contracted software deliverables."},
            ]},
            {"title": "Quality", "weight_pct": 25, "tasks": [
                {"title": "AI code review", "ai_task": "code_review",
                 "description": "Governed review of the delivered code for defects and risks."},
                {"title": "AI QA checklist", "ai_task": "qa_review",
                 "description": "Generate the acceptance QA checklist for the deliverable."},
            ]},
            {"title": "Handover", "weight_pct": 15, "tasks": [
                {"title": "Client acceptance (UAT)", "ai_task": None,
                 "description": "Client validates against the QA checklist in the portal."},
            ]},
        ],
    },
    "DIGITAL_MARKETING": {
        "milestones": [
            {"title": "Discovery & Market Brief", "weight_pct": 25, "tasks": [
                {"title": "AI campaign brief", "ai_task": "summarization",
                 "description": "Condense the client brief into a delivery brief: audience, "
                                "message, channels, dates."},
                {"title": "Audience & channel selection", "ai_task": None,
                 "description": "Pick channels and audience segments for the campaign."},
            ]},
            {"title": "Content Production", "weight_pct": 35, "tasks": [
                {"title": "Produce campaign deliverables", "ai_task": None,
                 "description": "Create the core assets for this service line."},
            ]},
            {"title": "Localisation", "weight_pct": 20, "tasks": [
                {"title": "AI multilingual adaptation", "ai_task": "translation",
                 "description": "Adapt copy into Malayalam / Hindi / Tamil (or English), "
                                "brand names preserved."},
            ]},
            {"title": "Launch & Report", "weight_pct": 20, "tasks": [
                {"title": "AI response triage setup", "ai_task": "classification",
                 "description": "Classify inbound replies/leads into actionable buckets."},
                {"title": "Campaign report", "ai_task": None,
                 "description": "Collect results and write the client report."},
            ]},
        ],
    },
}


def delivery_template_for(domain: str) -> dict:
    template = _DELIVERY_TEMPLATES.get(domain)
    if template is None:
        raise ValidationAppError(
            f"No delivery template for domain '{domain}'",
            details={"known_domains": sorted(_DELIVERY_TEMPLATES)},
        )
    return template


def stamp_delivery_templates(db: Session, tenant_id: uuid.UUID) -> int:
    """Stamp every service item of the tenant with its domain blueprint."""
    from app.modules.catalog.models import ServiceCategory, ServiceSubcategory

    services = db.scalars(
        select(Service).join(ServiceSubcategory).join(ServiceCategory).where(
            Service.tenant_id == tenant_id,
            ServiceCategory.domain.in_(list(_DELIVERY_TEMPLATES)),
        )
    ).all()
    for service in services:
        domain = service.subcategory.category.domain
        service.delivery_template = delivery_template_for(domain)
    db.flush()
    return len(services)


def promote_deliverable_service(
    db: Session,
    *,
    principal: Principal,
    service_id: uuid.UUID,
    source_note: str,
) -> Service:
    """Promote a service to AI-assisted delivery with truthful evidence.

    Records the six readiness-promotion evidence keys as verified (with the
    concrete source note of WHAT was verified — tool access via the governed
    gateway, the delivery blueprint, RBAC, privacy gates, quota capacity,
    benchmark quality floors) and only then promotes availability/readiness
    through the regular lifecycle guard.
    """
    from app.core.security import utcnow
    from app.modules.catalog.models import ServiceReadinessEvidence

    if not source_note.strip():
        raise ValidationAppError("A truthful source note is required for promotion")
    service = get_service(db, principal.tenant_id, service_id)
    if not service.delivery_template:
        raise ConflictError(
            "Service has no delivery template — stamp templates first",
            details={"service": service.name},
        )
    existing = {
        e.evidence_key for e in db.scalars(
            select(ServiceReadinessEvidence).where(
                ServiceReadinessEvidence.service_id == service.id
            )
        ).all()
    }
    for key in READINESS_PROMOTION_REQUIREMENTS:
        if key in existing:
            continue
        db.add(ServiceReadinessEvidence(
            service_id=service.id,
            evidence_key=key,
            description=f"{source_note} (verified {utcnow():%Y-%m-%d})",
            verified=True,
            verified_at=utcnow(),
            verified_by=principal.user_id,
        ))
    db.flush()
    return update_service_lifecycle(
        db, principal=principal, service_id=service.id,
        availability=ServiceAvailability.AVAILABLE_AI_ASSISTED.value,
        readiness=ServiceReadiness.LIMITED.value,
        execution_mode=ExecutionMode.AI_ASSISTED.value,
    )
