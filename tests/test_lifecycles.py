"""Catalog + commercial + delivery lifecycle tests (Phases 2, 5/6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.enums import (
    LeadStatus,
    ProjectLifecycleState,
    ServiceReadiness,
    TaskStatus,
    UserRole,
)
from app.core.errors import ConflictError, ValidationAppError
from app.modules.catalog import service as catalog
from app.modules.catalog.models import Service, ServiceReadinessEvidence
from app.modules.commercial import service as commercial
from app.modules.crm import service as crm
from app.modules.delivery import service as delivery
from app.modules.identity.service import Principal

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def founder(seed) -> Principal:
    return Principal(
        user_id=seed.admin.id, email=seed.admin.email, tenant_id=seed.tenant.id,
        role=UserRole.SUPER_ADMIN, client_id=None, session_id=seed.admin.id, csrf_token="",
    )


# ------------------------------------------------------------------ catalog

def _make_subcategory(db, seed):
    from app.modules.catalog.models import ServiceCategory, ServiceSubcategory

    category = ServiceCategory(
        tenant_id=seed.tenant.id, domain="SOFTWARE_ENGINEERING", code="9.9", name="Test Family"
    )
    db.add(category)
    db.flush()
    sub = ServiceSubcategory(category_id=category.id, code="9.9.1", name="Test Sub")
    db.add(sub)
    db.flush()
    return sub


def _make_service(db, seed, name: str) -> Service:
    return Service(tenant_id=seed.tenant.id, subcategory_id=_make_subcategory(db, seed).id, name=name)



def test_taxonomy_import_preserves_every_leaf(db, seed) -> None:
    stats = catalog.import_taxonomy(
        db,
        tenant_id=seed.tenant.id,
        md_path=REPO_ROOT / "docs" / "source_service_hierarchy.md",
        seed_csv_path=REPO_ROOT / "examples" / "service-readiness-seed.csv",
    )
    db.commit()
    assert stats["families"] == 19  # 10 software engineering + 9 digital marketing
    assert stats["subcategories"] == 76  # 39 SE + 37 DM
    assert stats["services"] == 224  # every preserved leaf entry (114 SE + 110 DM)
    # Idempotent: re-import skips everything.
    again = catalog.import_taxonomy(
        db, tenant_id=seed.tenant.id,
        md_path=REPO_ROOT / "docs" / "source_service_hierarchy.md",
        seed_csv_path=REPO_ROOT / "examples" / "service-readiness-seed.csv",
    )
    db.commit()
    assert again["services"] == 0


def test_default_readiness_is_planned_not_sellable(db, seed, founder) -> None:
    catalog.import_taxonomy(
        db, tenant_id=seed.tenant.id,
        md_path=REPO_ROOT / "docs" / "source_service_hierarchy.md",
        seed_csv_path=REPO_ROOT / "examples" / "service-readiness-seed.csv",
    )
    db.commit()
    service = db.scalar(select(Service).where(Service.name.ilike("%playwright%")))
    assert service is not None
    assert service.readiness == ServiceReadiness.PLANNED.value
    assert service.is_sellable_now is False


def test_quotable_guard_rejects_catalog_only_service(db, seed, founder) -> None:
    row = _make_service(db, seed, "Test Service")
    row.readiness = "PLANNED"
    row.availability = "CATALOG_ONLY"
    db.add(row)
    db.commit()
    with pytest.raises(ConflictError, match="truthful"):
        catalog.assert_quotable(row)


def test_readiness_promotion_requires_evidence(db, seed, founder) -> None:
    service = _make_service(db, seed, "Promotable Service")
    db.add(service)
    db.commit()
    with pytest.raises(ConflictError, match="evidence"):
        catalog.update_service_lifecycle(
            db, principal=founder, service_id=service.id, readiness="READY"
        )
    # Record all required evidence items, verified.
    for key in catalog.READINESS_PROMOTION_REQUIREMENTS:
        db.add(
            ServiceReadinessEvidence(
                service_id=service.id, evidence_key=key, verified=True,
                verified_by=seed.admin.id,
            )
        )
    db.commit()
    updated = catalog.update_service_lifecycle(
        db, principal=founder, service_id=service.id,
        readiness="READY", availability="AVAILABLE_MANUAL", sellable=True,
    )
    assert updated.is_sellable_now is True


# --------------------------------------------------------------- commercial


def _make_sellable_service(db, seed, name="Sellable Web App") -> Service:
    service = _make_service(db, seed, name)
    db.add(service)
    db.flush()
    for key in catalog.READINESS_PROMOTION_REQUIREMENTS:
        db.add(ServiceReadinessEvidence(service_id=service.id, evidence_key=key, verified=True))
    db.flush()
    catalog.update_service_lifecycle(
        db, principal=Principal(
            user_id=seed.admin.id, email=seed.admin.email, tenant_id=seed.tenant.id,
            role=UserRole.SUPER_ADMIN, client_id=None, session_id=seed.admin.id, csrf_token="",
        ),
        service_id=service.id, readiness="READY", availability="AVAILABLE_AI_ASSISTED",
        sellable=True,
    )
    return service


def test_full_commercial_lifecycle(db, seed, founder) -> None:
    """Lead → qualification → client → proposal → contract → scope freeze →
    invoices → payment reconciliation (SRS §15)."""
    service = _make_sellable_service(db, seed)
    crm.create_client(db, principal=founder, display_name="Lifecycle Co")
    lead = crm.create_lead(
        db, principal=founder, title="Website for Lifecycle Co",
        contact_email="boss@lifecycle.example", budget_minor=500000, feasibility_score=85,
    )
    crm.qualify_lead(db, tenant_id=seed.tenant.id, lead_id=lead.id, to_status=LeadStatus.CONTACTED)
    crm.qualify_lead(db, tenant_id=seed.tenant.id, lead_id=lead.id, to_status=LeadStatus.QUALIFIED,
                     feasibility_score=88)
    crm.qualify_lead(db, tenant_id=seed.tenant.id, lead_id=lead.id, to_status=LeadStatus.DISCOVERY)
    crm.qualify_lead(db, tenant_id=seed.tenant.id, lead_id=lead.id, to_status=LeadStatus.PROPOSAL_SENT)
    crm.qualify_lead(db, tenant_id=seed.tenant.id, lead_id=lead.id, to_status=LeadStatus.WON)
    won_client = crm.convert_lead_to_client(db, tenant_id=seed.tenant.id, lead_id=lead.id)
    db.commit()

    proposal = commercial.create_proposal(
        db, principal=founder, client_id=won_client.id, title="Website build",
        amount_minor=500000, service_ids=[service.id],
    )
    with pytest.raises(ConflictError):
        commercial.create_contract_from_proposal(
            db, tenant_id=seed.tenant.id, proposal_id=proposal.id
        )  # not accepted yet
    commercial.transition_proposal(db, tenant_id=seed.tenant.id, proposal_id=proposal.id, to_status="SENT")
    commercial.transition_proposal(db, tenant_id=seed.tenant.id, proposal_id=proposal.id, to_status="ACCEPTED")
    contract = commercial.create_contract_from_proposal(
        db, tenant_id=seed.tenant.id, proposal_id=proposal.id
    )
    commercial.sign_contract(db, tenant_id=seed.tenant.id, contract_id=contract.id)
    baseline = [{"req": "5 pages"}, {"req": "contact form"}, {"req": "SEO basics"}]
    commercial.freeze_scope(db, tenant_id=seed.tenant.id, contract_id=contract.id, baseline=baseline)
    assert contract.scope_baseline_hash
    assert contract.scope_frozen_at is not None

    project = delivery.create_project(
        db, principal=founder, client_id=won_client.id, name="Lifecycle Website",
        contract_id=contract.id,
    )
    invoices = commercial.create_milestone_invoices(
        db, tenant_id=seed.tenant.id, contract_id=contract.id, project_id=project.id,
        split=[30, 30, 40], prefix="AKN-2026-",
    )
    assert [i.amount_minor for i in invoices] == [150000, 150000, 200000]
    commercial.issue_invoice(db, tenant_id=seed.tenant.id, invoice_id=invoices[0].id)
    payment = commercial.record_payment(
        db, principal=founder, invoice_id=invoices[0].id, amount_minor=150000,
        reference="UPI/123",
    )
    assert payment.status == "RECORDED"
    commercial.reconcile_payment(db, principal=founder, payment_id=payment.id, accept=True)
    assert invoices[0].status == "PAID"


def test_proposal_cannot_quote_non_sellable_service(db, seed, founder) -> None:
    client = crm.create_client(db, principal=founder, display_name="Strict Co")
    plain = _make_service(db, seed, "Planned Only")
    db.add(plain)
    db.commit()
    with pytest.raises(ConflictError, match="truthful"):
        commercial.create_proposal(
            db, principal=founder, client_id=client.id, title="X",
            amount_minor=100, service_ids=[plain.id],
        )


def test_change_request_requires_frozen_scope(db, seed, founder) -> None:
    client = crm.create_client(db, principal=founder, display_name="Scope Co")
    proposal = commercial.create_proposal(
        db, principal=founder, client_id=client.id, title="Y", amount_minor=1000,
    )
    commercial.transition_proposal(db, tenant_id=seed.tenant.id, proposal_id=proposal.id, to_status="SENT")
    commercial.transition_proposal(db, tenant_id=seed.tenant.id, proposal_id=proposal.id, to_status="ACCEPTED")
    contract = commercial.create_contract_from_proposal(
        db, tenant_id=seed.tenant.id, proposal_id=proposal.id
    )
    with pytest.raises(ConflictError, match="frozen"):
        commercial.create_change_request(
            db, tenant_id=seed.tenant.id, contract_id=contract.id, title="Add feature",
        )


# ---------------------------------------------------------------- delivery


def test_project_lifecycle_gates(db, seed, founder) -> None:
    """STAGING_UAT requires a preview; PRODUCTION_HANDOFF requires accepted UAT."""
    client = crm.create_client(db, principal=founder, display_name="Gate Co")
    project = delivery.create_project(db, principal=founder, client_id=client.id, name="Gated")
    delivery.transition_project(db, tenant_id=seed.tenant.id, project_id=project.id,
                                to_state=ProjectLifecycleState.LEAD_QUALIFIED)
    delivery.transition_project(db, tenant_id=seed.tenant.id, project_id=project.id,
                                to_state=ProjectLifecycleState.PROPOSAL_APPROVED)
    delivery.transition_project(db, tenant_id=seed.tenant.id, project_id=project.id,
                                to_state=ProjectLifecycleState.CONTRACT_SIGNED)
    delivery.transition_project(db, tenant_id=seed.tenant.id, project_id=project.id,
                                to_state=ProjectLifecycleState.ASSET_INTAKE)
    delivery.transition_project(db, tenant_id=seed.tenant.id, project_id=project.id,
                                to_state=ProjectLifecycleState.ARCHITECTURE_AND_WIREFRAME)
    delivery.transition_project(db, tenant_id=seed.tenant.id, project_id=project.id,
                                to_state=ProjectLifecycleState.DEVELOPMENT_SPRINT)
    delivery.transition_project(db, tenant_id=seed.tenant.id, project_id=project.id,
                                to_state=ProjectLifecycleState.QA_AND_SECURITY_GATE)
    with pytest.raises(ConflictError, match="staging preview"):
        delivery.transition_project(db, tenant_id=seed.tenant.id, project_id=project.id,
                                    to_state=ProjectLifecycleState.STAGING_UAT)
    delivery.create_staging_preview(db, tenant_id=seed.tenant.id, project_id=project.id,
                                    url="https://staging.example/p")
    delivery.transition_project(db, tenant_id=seed.tenant.id, project_id=project.id,
                                to_state=ProjectLifecycleState.STAGING_UAT)
    with pytest.raises(ConflictError, match="UAT"):
        delivery.transition_project(db, tenant_id=seed.tenant.id, project_id=project.id,
                                    to_state=ProjectLifecycleState.PRODUCTION_HANDOFF)
    delivery.record_uat_decision(db, principal=founder, project_id=project.id,
                                 checklist=[{"item": "pages ok", "checked": True}],
                                 decision="ACCEPTED")
    delivery.transition_project(db, tenant_id=seed.tenant.id, project_id=project.id,
                                to_state=ProjectLifecycleState.PRODUCTION_HANDOFF)


def test_illegal_project_transition_rejected(db, seed, founder) -> None:
    client = crm.create_client(db, principal=founder, display_name="Jump Co")
    project = delivery.create_project(db, principal=founder, client_id=client.id, name="Jump")
    with pytest.raises(ConflictError, match="Illegal"):
        delivery.transition_project(db, tenant_id=seed.tenant.id, project_id=project.id,
                                    to_state=ProjectLifecycleState.CLOSED)


def test_task_requires_verification_before_done(db, seed, founder) -> None:
    client = crm.create_client(db, principal=founder, display_name="Task Co")
    project = delivery.create_project(db, principal=founder, client_id=client.id, name="Tasks")
    task = delivery.create_task(db, tenant_id=seed.tenant.id, project_id=project.id,
                                title="Implement login")
    delivery.transition_task(db, tenant_id=seed.tenant.id, task_id=task.id,
                             to_status=TaskStatus.SPECIFIED)
    delivery.transition_task(db, tenant_id=seed.tenant.id, task_id=task.id,
                             to_status=TaskStatus.IN_PROGRESS)
    delivery.transition_task(db, tenant_id=seed.tenant.id, task_id=task.id,
                             to_status=TaskStatus.REVIEW)
    # REVIEW → DONE is illegal: the VERIFIED step is mandatory.
    with pytest.raises(ConflictError, match="Illegal task transition REVIEW → DONE"):
        delivery.transition_task(db, tenant_id=seed.tenant.id, task_id=task.id,
                                 to_status=TaskStatus.DONE)
    delivery.transition_task(db, tenant_id=seed.tenant.id, task_id=task.id,
                             to_status=TaskStatus.VERIFIED)
    delivery.transition_task(db, tenant_id=seed.tenant.id, task_id=task.id,
                             to_status=TaskStatus.DONE)
    assert task.completed_at is not None


def test_task_idempotency_key_deduplicates(db, seed, founder) -> None:
    client = crm.create_client(db, principal=founder, display_name="Idem Co")
    project = delivery.create_project(db, principal=founder, client_id=client.id, name="Idem")
    first = delivery.create_task(db, tenant_id=seed.tenant.id, project_id=project.id,
                                 title="Once", idempotency_key="idem-1")
    second = delivery.create_task(db, tenant_id=seed.tenant.id, project_id=project.id,
                                  title="Once again", idempotency_key="idem-1")
    assert first.id == second.id


# ---------------------------------------------------------------- settings


def test_settings_seeded_and_update_validated(db, seed, app, founder) -> None:
    from app.modules.ops import settings_service

    assert settings_service.get_setting(db, "brand_name") == "Aknja Digital"
    assert settings_service.get_setting(db, "warranty_days") == 30
    assert settings_service.get_setting(db, "payment_milestone_split") == [30, 30, 40]
    assert settings_service.get_setting(db, "tax_mode") == "NON_GST_EXEMPT"

    with pytest.raises(ValidationAppError):
        settings_service.update_setting(
            db, principal=founder, key="warranty_days", value="not-a-number"
        )
    updated = settings_service.update_setting(
        db, principal=founder, key="warranty_days", value=45
    )
    assert updated.value_json == 45
    db.commit()
    # Cache invalidated → new value visible.
    assert settings_service.get_setting(db, "warranty_days") == 45


def test_protected_setting_not_runtime_editable(db, seed, founder) -> None:
    from app.modules.ops import settings_service

    with pytest.raises(ValidationAppError, match="protected"):
        settings_service.update_setting(
            db, principal=founder, key="anti_ban_guard_locked", value=False
        )


def test_settings_api_and_audit(db, seed, admin_client) -> None:
    listed = admin_client.get("/api/v1/admin/settings")
    assert listed.status_code == 200
    keys = {s["key"] for s in listed.json()}
    assert "brand_name" in keys and "invoice_prefix" in keys

    resp = admin_client.put("/api/v1/admin/settings", json={"key": "quote_validity_days", "value": 20})
    assert resp.status_code == 200
    # The change is audited.
    audit = admin_client.get("/api/v1/audit-events")
    actions = [e["action"] for e in audit.json()]
    assert "settings.updated" in actions
