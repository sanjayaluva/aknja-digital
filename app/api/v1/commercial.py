"""Commercial API: proposals, contracts, change requests, invoices, payments."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CsrfDep, CurrentPrincipal, DbDep, WritePrincipal
from app.modules.commercial import service as commercial
from app.modules.ops.settings_service import get_setting

router = APIRouter(tags=["commercial"])


class ProposalCreate(BaseModel):
    client_id: uuid.UUID
    title: str = Field(min_length=3, max_length=200)
    amount_minor: int = Field(ge=0)
    currency: str = "INR"
    body: str = ""
    service_ids: list[uuid.UUID] = []
    persona: str = "solo_developer"


class StatusChange(BaseModel):
    to_status: str


class ContractCreate(BaseModel):
    proposal_id: uuid.UUID
    warranty_days: int = 30


class ScopeFreeze(BaseModel):
    baseline: list[dict]


class ChangeRequestCreate(BaseModel):
    title: str = Field(min_length=3)
    description: str = ""
    quote_amount_minor: int = Field(default=0, ge=0)
    currency: str = "INR"


class ChangeRequestDecide(BaseModel):
    approved: bool


class InvoiceGenerate(BaseModel):
    contract_id: uuid.UUID
    project_id: uuid.UUID | None = None


class PaymentCreate(BaseModel):
    amount_minor: int = Field(gt=0)
    method: str = "BANK_TRANSFER"
    reference: str = ""
    notes: str = ""


class PaymentReconcile(BaseModel):
    accept: bool


def _proposal_out(p) -> dict:
    return {
        "id": str(p.id), "number": p.number, "title": p.title, "status": p.status,
        "client_id": str(p.client_id), "amount_minor": p.amount_minor,
        "currency": p.currency, "valid_until": p.valid_until.isoformat() if p.valid_until else None,
    }


def _contract_out(c) -> dict:
    return {
        "id": str(c.id), "number": c.number, "title": c.title, "status": c.status,
        "client_id": str(c.client_id), "amount_minor": c.amount_minor,
        "signed_at": c.signed_at.isoformat() if c.signed_at else None,
        "scope_frozen_at": c.scope_frozen_at.isoformat() if c.scope_frozen_at else None,
        "scope_baseline_hash": c.scope_baseline_hash,
    }


def _invoice_out(i) -> dict:
    return {
        "id": str(i.id), "number": i.number, "status": i.status,
        "client_id": str(i.client_id), "amount_minor": i.amount_minor,
        "paid_amount_minor": i.paid_amount_minor, "amount_due_minor": i.amount_due_minor,
        "currency": i.currency, "tax_mode": i.tax_mode, "sac_code": i.sac_code,
    }


@router.get("/proposals")
def list_proposals(db: DbDep, principal: CurrentPrincipal) -> list[dict]:
    from sqlalchemy import select

    from app.modules.commercial.models import Proposal

    rows = db.scalars(
        select(Proposal)
        .where(Proposal.tenant_id == principal.tenant_id)
        .order_by(Proposal.created_at.desc())
    )
    return [_proposal_out(p) for p in rows]


@router.post("/proposals", status_code=201)
def create_proposal(body: ProposalCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep) -> dict:
    validity = int(get_setting(db, "quote_validity_days", 15))
    proposal = commercial.create_proposal(
        db,
        principal=principal,
        client_id=body.client_id,
        title=body.title,
        amount_minor=body.amount_minor,
        currency=body.currency,
        body=body.body,
        service_ids=body.service_ids,
        validity_days=validity,
        persona=body.persona,
    )
    return _proposal_out(proposal)


@router.post("/proposals/{proposal_id}/transition")
def transition_proposal(
    proposal_id: uuid.UUID, body: StatusChange, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    p = commercial.transition_proposal(
        db, tenant_id=principal.tenant_id, proposal_id=proposal_id, to_status=body.to_status
    )
    return _proposal_out(p)


@router.post("/contracts", status_code=201)
def create_contract(body: ContractCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep) -> dict:
    warranty = int(get_setting(db, "warranty_days", 30))
    contract = commercial.create_contract_from_proposal(
        db, tenant_id=principal.tenant_id, proposal_id=body.proposal_id, warranty_days=warranty
    )
    return _contract_out(contract)


@router.post("/contracts/{contract_id}/sign")
def sign_contract(contract_id: uuid.UUID, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep) -> dict:
    return _contract_out(commercial.sign_contract(db, tenant_id=principal.tenant_id, contract_id=contract_id))


@router.post("/contracts/{contract_id}/freeze-scope")
def freeze_scope(
    contract_id: uuid.UUID, body: ScopeFreeze, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    return _contract_out(
        commercial.freeze_scope(db, tenant_id=principal.tenant_id, contract_id=contract_id, baseline=body.baseline)
    )


@router.post("/contracts/{contract_id}/change-requests", status_code=201)
def create_change_request(
    contract_id: uuid.UUID, body: ChangeRequestCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    cr = commercial.create_change_request(
        db,
        tenant_id=principal.tenant_id,
        contract_id=contract_id,
        title=body.title,
        description=body.description,
        quote_amount_minor=body.quote_amount_minor,
        currency=body.currency,
    )
    return {"id": str(cr.id), "title": cr.title, "status": cr.status}


@router.post("/change-requests/{change_request_id}/decide")
def decide_change_request(
    change_request_id: uuid.UUID, body: ChangeRequestDecide, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    cr = commercial.decide_change_request(
        db, tenant_id=principal.tenant_id, change_request_id=change_request_id, approved=body.approved
    )
    return {"id": str(cr.id), "title": cr.title, "status": cr.status}


@router.post("/invoices/generate", status_code=201)
def generate_invoices(
    body: InvoiceGenerate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> list[dict]:
    split = get_setting(db, "payment_milestone_split", [30, 30, 40])
    prefix = get_setting(db, "invoice_prefix", "AKN-2026-")
    tax_mode = get_setting(db, "tax_mode", "NON_GST_EXEMPT")
    sac = get_setting(db, "default_sac_code", "998314")
    invoices = commercial.create_milestone_invoices(
        db,
        tenant_id=principal.tenant_id,
        contract_id=body.contract_id,
        project_id=body.project_id,
        split=[int(x) for x in split],
        prefix=str(prefix),
        tax_mode=str(tax_mode),
        sac_code=str(sac),
    )
    return [_invoice_out(i) for i in invoices]


@router.get("/invoices")
def list_invoices(db: DbDep, principal: CurrentPrincipal, client_id: uuid.UUID | None = None) -> list[dict]:
    return [
        _invoice_out(i) for i in commercial.list_invoices(db, principal.tenant_id, client_id)
    ]


@router.post("/invoices/{invoice_id}/issue")
def issue_invoice(invoice_id: uuid.UUID, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep) -> dict:
    return _invoice_out(commercial.issue_invoice(db, tenant_id=principal.tenant_id, invoice_id=invoice_id))


@router.post("/invoices/{invoice_id}/payments", status_code=201)
def record_payment(
    invoice_id: uuid.UUID, body: PaymentCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    payment = commercial.record_payment(
        db,
        principal=principal,
        invoice_id=invoice_id,
        amount_minor=body.amount_minor,
        method=body.method,
        reference=body.reference,
        notes=body.notes,
    )
    return {"id": str(payment.id), "status": payment.status, "amount_minor": payment.amount_minor}


@router.post("/payments/{payment_id}/reconcile")
def reconcile_payment(
    payment_id: uuid.UUID, body: PaymentReconcile, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    payment = commercial.reconcile_payment(
        db, principal=principal, payment_id=payment_id, accept=body.accept
    )
    return {"id": str(payment.id), "status": payment.status}
