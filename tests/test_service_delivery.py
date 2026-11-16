"""Catalog -> delivery flow (T-026): service items carry a delivery blueprint
that instantiates a project (milestones + tasks, AI steps wired to governed
task profiles); AI runs register artifacts and park for human verification;
readiness promotion requires truthful evidence.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, AuthClient

REPO_ROOT = Path(__file__).resolve().parent.parent


def _import_taxonomy(db, seed) -> None:
    from app.modules.catalog import service as catalog

    catalog.import_taxonomy(
        db, tenant_id=seed.tenant.id,
        md_path=REPO_ROOT / "docs" / "source_service_hierarchy.md",
        seed_csv_path=REPO_ROOT / "examples" / "service-readiness-seed.csv",
    )
    db.commit()


def _stamped(db, seed) -> None:
    from app.modules.catalog import service as catalog

    _import_taxonomy(db, seed)
    n = catalog.stamp_delivery_templates(db, seed.tenant.id)
    db.commit()
    assert n == 224


def _founder_principal(seed):
    from app.core.enums import UserRole
    from app.modules.identity.service import Principal

    return Principal(
        user_id=seed.admin.id, email=seed.admin.email, tenant_id=seed.tenant.id,
        role=UserRole.SUPER_ADMIN, client_id=None, session_id=seed.admin.id,
        csrf_token="seed",
    )


def _service_by_name(db, seed, name: str):
    from app.modules.catalog.models import Service

    return db.scalars(
        select(Service).where(Service.tenant_id == seed.tenant.id, Service.name == name)
    ).one()


def _client(db, seed):
    from app.modules.crm import service as crm

    client = crm.create_client(db, principal=_founder_principal(seed),
                               display_name="Delivery Co")
    db.commit()
    return client


# --- templates -------------------------------------------------------------------


def test_templates_stamp_every_service_both_domains(db, seed) -> None:
    _stamped(db, seed)
    from app.modules.catalog.models import Service, ServiceSubcategory

    services = db.scalars(
        select(Service).join(ServiceSubcategory)
    ).all()
    assert len(services) == 224
    for service in services:
        template = service.delivery_template
        assert template and template["milestones"], service.name
        weights = [m["weight_pct"] for m in template["milestones"]]
        assert sum(weights) == 100, (service.name, weights)
        ai_tasks = {t.get("ai_task") for m in template["milestones"]
                    for t in m["tasks"] if t.get("ai_task")}
        domain = service.subcategory.category.domain
        if domain == "SOFTWARE_ENGINEERING":
            assert {"requirements", "code_review", "qa_review"} <= ai_tasks
        else:
            assert {"summarization", "translation", "classification"} <= ai_tasks
        # no template may promise a lane the pool cannot serve above its floor
        assert "proposal_draft" not in ai_tasks


def test_promotion_requires_template_and_truthful_note(db, seed) -> None:
    _stamped(db, seed)
    from app.core.errors import ConflictError, ValidationAppError
    from app.modules.catalog import service as catalog

    service = _service_by_name(db, seed, "Single Page Applications (SPAs)")
    principal = _founder_principal(seed)

    # unstamped service cannot promote
    unstamped = _service_by_name(db, seed, "Single Page Applications (SPAs)")
    unstamped.delivery_template = None
    db.commit()
    with pytest.raises(ConflictError, match="no delivery template"):
        catalog.promote_deliverable_service(
            db, principal=principal, service_id=service.id, source_note="x")
    _stamped(db, seed)

    # empty note is not truthful evidence
    with pytest.raises(ValidationAppError, match="source note"):
        catalog.promote_deliverable_service(
            db, principal=principal, service_id=service.id, source_note="  ")

    promoted = catalog.promote_deliverable_service(
        db, principal=principal, service_id=service.id,
        source_note="T-026 verification: governed gateway tool access, blueprint, "
                    "RBAC, privacy gates, quota capacity, benchmark floors",
    )
    db.commit()
    assert promoted.availability == "AVAILABLE_AI_ASSISTED"
    assert promoted.readiness == "LIMITED"
    assert promoted.execution_mode == "AI_ASSISTED"

    from app.modules.catalog.models import ServiceReadinessEvidence

    evidence = db.scalars(
        select(ServiceReadinessEvidence)
        .where(ServiceReadinessEvidence.service_id == service.id)
    ).all()
    assert {e.evidence_key for e in evidence} >= {
        "verified_tool_access", "workflow_defined", "permissions_verified",
        "privacy_checked", "quota_capacity_checked", "qa_checklist_defined",
    }
    assert all(e.verified for e in evidence)


# --- project instantiation ---------------------------------------------------------


def test_start_project_instantiates_both_domain_blueprints(db, seed) -> None:
    _stamped(db, seed)
    from app.modules.delivery import service as delivery
    from app.modules.delivery.models import Milestone, Task

    principal = _founder_principal(seed)
    client = _client(db, seed)

    se_service = _service_by_name(db, seed, "Single Page Applications (SPAs)")
    se_project = delivery.start_project_from_service(
        db, principal=principal, client_id=client.id, service_id=se_service.id,
        name="Showcase App", brief="A bakery ordering PWA with WhatsApp notifications.",
    )
    dm_service = _service_by_name(db, seed, "High-Converting Landing Page Sales Copy")
    dm_project = delivery.start_project_from_service(
        db, principal=principal, client_id=client.id, service_id=dm_service.id,
        name="Launch Marketing", brief="Launch campaign for the Showcase App.",
    )
    db.commit()

    for project, service in ((se_project, se_service), (dm_project, dm_service)):
        assert project.service_id == service.id
        milestones = db.scalars(
            select(Milestone).where(Milestone.project_id == project.id)
            .order_by(Milestone.sort_order)
        ).all()
        assert len(milestones) == 4
        assert sum(m.weight_pct for m in milestones) == 100
        tasks = db.scalars(
            select(Task).where(Task.project_id == project.id)
        ).all()
        assert len(tasks) == 6
        assert all(t.milestone_id for t in tasks)  # every task is on a milestone
        assert all(t.status == "BACKLOG" for t in tasks)

    se_ai = {t.ai_task for t in db.scalars(select(Task).where(
        Task.project_id == se_project.id)).all()}
    dm_ai = {t.ai_task for t in db.scalars(select(Task).where(
        Task.project_id == dm_project.id)).all()}
    assert {"requirements", "code_review", "qa_review"} <= se_ai
    assert {"summarization", "translation", "classification"} <= dm_ai


def test_same_service_starts_independent_projects(db, seed) -> None:
    """The task idempotency key is per-project: a service item can back many
    concurrent client engagements (regression: the key used to be per-service
    and the second project crashed on task None)."""
    _stamped(db, seed)
    from app.modules.delivery import service as delivery
    from app.modules.delivery.models import Task

    principal = _founder_principal(seed)
    client = _client(db, seed)
    service = _service_by_name(db, seed, "High-Converting Landing Page Sales Copy")
    p1 = delivery.start_project_from_service(
        db, principal=principal, client_id=client.id, service_id=service.id,
        name="Engagement A", brief="First client campaign.")
    db.commit()
    p2 = delivery.start_project_from_service(
        db, principal=principal, client_id=client.id, service_id=service.id,
        name="Engagement B", brief="Second client campaign.")
    db.commit()
    t1 = db.scalars(select(Task).where(Task.project_id == p1.id)).all()
    t2 = db.scalars(select(Task).where(Task.project_id == p2.id)).all()
    assert len(t1) == 6 and len(t2) == 6
    assert {t.id for t in t1}.isdisjoint({t.id for t in t2})
    assert all(t.milestone_id for t in t2)  # full blueprint, not idempotent stubs


def test_start_project_rejects_unstamped_service(db, seed) -> None:
    _import_taxonomy(db, seed)  # no stamping
    from app.core.errors import ConflictError
    from app.modules.delivery import service as delivery

    principal = _founder_principal(seed)
    client = _client(db, seed)
    service = _service_by_name(db, seed, "High-Converting Landing Page Sales Copy")
    with pytest.raises(ConflictError, match="no delivery template"):
        delivery.start_project_from_service(
            db, principal=principal, client_id=client.id, service_id=service.id,
            name="X", brief="Y",
        )


# --- AI task execution --------------------------------------------------------------


def _mock_llm(monkeypatch, text: str, status: str = "SUCCEEDED") -> None:
    from app.modules.ai import gateway as gateway_module
    from app.modules.ai import inference as inference_module

    class _Result:
        pass

    def _fake_complete(_db, **kwargs):
        r = _Result()
        r.status = status
        r.text = text
        r.provider = "groq"
        r.model = "openai/gpt-oss-20b"
        r.latency_ms = 42
        r.reason = "no eligible lane above quality floor" if status != "SUCCEEDED" else ""
        r.attempts = []
        return r

    monkeypatch.setattr(inference_module, "llm_complete", _fake_complete)
    monkeypatch.setattr(gateway_module, "llm_complete", _fake_complete)


def _ai_task(db, project_id, ai_task: str):
    from app.modules.delivery.models import Task

    return db.scalars(
        select(Task).where(Task.project_id == project_id, Task.ai_task == ai_task)
    ).first()


def test_run_ai_task_registers_artifact_and_parks_for_review(db, seed, monkeypatch) -> None:
    _stamped(db, seed)
    from app.modules.delivery import service as delivery
    from app.modules.delivery.models import Artifact

    principal = _founder_principal(seed)
    client = _client(db, seed)
    service = _service_by_name(db, seed, "Single Page Applications (SPAs)")
    project = delivery.start_project_from_service(
        db, principal=principal, client_id=client.id, service_id=service.id,
        name="Showcase App", brief="Bakery ordering PWA with WhatsApp notifications.",
    )
    db.commit()

    _mock_llm(monkeypatch, '[{"id": "R1", "requirement": "order form", "priority": "HIGH"}]')
    task, artifact, outcome = delivery.run_ai_task(
        db, principal=principal, task_id=_ai_task(db, project.id, "requirements").id,
    )
    db.commit()

    assert outcome == "SUCCEEDED"
    assert task.status == "REVIEW"  # legal walk BACKLOG->SPECIFIED->IN_PROGRESS->REVIEW
    assert artifact is not None and artifact.title == "[AI] AI requirements extraction"
    assert "order form" in (artifact.content or "")
    artifacts = db.scalars(select(Artifact).where(
        Artifact.project_id == project.id)).all()
    assert len(artifacts) == 1
    # DONE still requires the human verification chain
    from app.core.errors import ConflictError
    from app.modules.delivery.models import TaskStatus

    with pytest.raises(ConflictError, match="REVIEW"):
        delivery.transition_task(db, tenant_id=seed.tenant.id, task_id=task.id,
                                 to_status=TaskStatus.DONE)
    delivery.transition_task(db, tenant_id=seed.tenant.id, task_id=task.id,
                             to_status=TaskStatus.VERIFIED)
    delivery.transition_task(db, tenant_id=seed.tenant.id, task_id=task.id,
                             to_status=TaskStatus.DONE)
    db.commit()


def test_run_ai_task_pending_is_governed_not_an_error(db, seed, monkeypatch) -> None:
    """PENDING_MANUAL (no lane above the quality floor) parks the task with the
    reason — never a silent degrade and never a crash."""
    _stamped(db, seed)
    from app.modules.delivery import service as delivery

    principal = _founder_principal(seed)
    client = _client(db, seed)
    service = _service_by_name(db, seed, "High-Converting Landing Page Sales Copy")
    project = delivery.start_project_from_service(
        db, principal=principal, client_id=client.id, service_id=service.id,
        name="Launch Marketing", brief="Campaign for the app.",
    )
    db.commit()

    _mock_llm(monkeypatch, "", status="PENDING_MANUAL")
    task, artifact, outcome = delivery.run_ai_task(
        db, principal=principal, task_id=_ai_task(db, project.id, "summarization").id,
    )
    db.commit()
    assert artifact is None
    assert "PENDING_MANUAL" in outcome
    assert task.status == "REVIEW"


# --- admin surface -------------------------------------------------------------------


def test_admin_start_project_form_and_run_ai(db, app, seed, monkeypatch) -> None:
    _stamped(db, seed)
    _client(db, seed)  # the client the project is started for
    admin = AuthClient(app, ADMIN_EMAIL, ADMIN_PASSWORD)

    from sqlalchemy import select as sel

    from app.modules.crm.models import Client
    client_row = db.scalars(sel(Client)).first()
    service = _service_by_name(db, seed, "Single Page Applications (SPAs)")

    # the start form lists clients and both domains
    form = admin.get("/admin/projects/new")
    assert form.status_code == 200
    assert "Software Engineering" in form.text and "Digital Marketing" in form.text

    resp = admin.post("/admin/projects/new", data={
        "client_id": str(client_row.id), "service_id": str(service.id),
        "name": "Showcase App", "brief": "Bakery ordering PWA.",
        "csrf_token": admin.csrf,
    })
    # the TestClient follows the 303 to the project page
    assert resp.status_code == 200
    assert "AI requirements extraction" in resp.text
    assert "Run AI" in resp.text

    # run the AI step through the real route (inference mocked)
    _mock_llm(monkeypatch, "AI QA checklist: 1) order form 2) WhatsApp flow")
    from app.modules.delivery.models import Task

    task = db.scalars(sel(Task).where(Task.ai_task == "qa_review")).first()
    run = admin.post(f"/admin/projects/{task.project_id}/tasks/{task.id}/run-ai",
                     data={"csrf_token": admin.csrf})
    # followed redirect lands on the project page with the artifact visible
    assert run.status_code == 200
    assert "AI QA checklist" in run.text
