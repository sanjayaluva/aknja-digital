"""Commercial service: proposals, contracts, scope freeze, change requests,
invoices and manual payment reconciliation (docs/08, SRS §15)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.security import canonical_payload_hash, utcnow
from app.modules.catalog.service import assert_quotable
from app.modules.commercial.models import ChangeRequest, Contract, Invoice, Payment, Proposal
from app.modules.crm.models import Client
from app.modules.identity.service import Principal

PROPOSAL_TRANSITIONS = {
    "DRAFT": {"SENT", "WITHDRAWN"},
    "SENT": {"ACCEPTED", "REJECTED", "EXPIRED", "WITHDRAWN"},
    "ACCEPTED": set(),
    "REJECTED": {"DRAFT"},
    "EXPIRED": {"DRAFT"},
    "WITHDRAWN": set(),
}


def _get_client(db: Session, tenant_id: uuid.UUID, client_id: uuid.UUID) -> Client:
    client = db.get(Client, client_id)
    if client is None or client.tenant_id != tenant_id:
        raise NotFoundError("Client not found")
    return client


def _next_number(db: Session, tenant_id: uuid.UUID, table, prefix: str) -> str:
    count = db.scalar(
        select(func.count()).select_from(table).where(table.tenant_id == tenant_id)
    )
    return f"{prefix}{(count or 0) + 1:04d}"


def create_proposal(
    db: Session,
    *,
    principal: Principal,
    client_id: uuid.UUID,
    title: str,
    amount_minor: int,
    currency: str = "INR",
    body: str = "",
    service_ids: list[uuid.UUID] | None = None,
    validity_days: int = 15,
    persona: str = "solo_developer",
) -> Proposal:
    from app.modules.catalog.models import Service

    _get_client(db, principal.tenant_id, client_id)
    if amount_minor < 0:
        raise ValidationAppError("amount_minor must be >= 0")
    # Every quoted service must be truthfully sellable right now.
    for sid in service_ids or []:
        service = db.get(Service, sid)
        if service is None or service.tenant_id != principal.tenant_id:
            raise NotFoundError(f"Service {sid} not found")
        assert_quotable(service)
    number = _next_number(db, principal.tenant_id, Proposal, "PRP-")
    proposal = Proposal(
        tenant_id=principal.tenant_id,
        client_id=client_id,
        number=number,
        title=title,
        body=body,
        currency=currency,
        amount_minor=amount_minor,
        valid_until=utcnow() + timedelta(days=validity_days),
        persona=persona,
        line_items=[{"service_id": str(s)} for s in (service_ids or [])],
    )
    db.add(proposal)
    db.flush()
    return proposal


def transition_proposal(
    db: Session, *, tenant_id: uuid.UUID, proposal_id: uuid.UUID, to_status: str
) -> Proposal:
    proposal = db.get(Proposal, proposal_id)
    if proposal is None or proposal.tenant_id != tenant_id:
        raise NotFoundError("Proposal not found")
    if to_status not in PROPOSAL_TRANSITIONS.get(proposal.status, set()):
        raise ConflictError(
            f"Illegal proposal transition {proposal.status} → {to_status}",
        )
    if to_status == "SENT":
        proposal.sent_at = utcnow()
    if to_status in ("ACCEPTED", "REJECTED"):
        proposal.decided_at = utcnow()
    if to_status == "ACCEPTED" and proposal.valid_until and utcnow() > proposal.valid_until:
        raise ConflictError("Proposal validity has expired — client must request a new quote")
    proposal.status = to_status
    db.flush()
    return proposal


def create_contract_from_proposal(
    db: Session, *, tenant_id: uuid.UUID, proposal_id: uuid.UUID, warranty_days: int = 30
) -> Contract:
    proposal = db.get(Proposal, proposal_id)
    if proposal is None or proposal.tenant_id != tenant_id:
        raise NotFoundError("Proposal not found")
    if proposal.status != "ACCEPTED":
        raise ConflictError("Contract requires an ACCEPTED proposal")
    existing = db.scalar(select(Contract).where(Contract.proposal_id == proposal.id))
    if existing is not None:
        raise ConflictError("A contract already exists for this proposal")
    number = _next_number(db, tenant_id, Contract, "CTR-")
    contract = Contract(
        tenant_id=tenant_id,
        proposal_id=proposal.id,
        client_id=proposal.client_id,
        number=number,
        title=proposal.title,
        body=proposal.body,
        currency=proposal.currency,
        amount_minor=proposal.amount_minor,
        warranty_days=warranty_days,
    )
    db.add(contract)
    db.flush()
    return contract


def sign_contract(db: Session, *, tenant_id: uuid.UUID, contract_id: uuid.UUID) -> Contract:
    contract = _get_contract(db, tenant_id, contract_id)
    if contract.status not in ("DRAFT", "SENT"):
        raise ConflictError(f"Cannot sign contract in status {contract.status}")
    contract.status = "SIGNED"
    contract.signed_at = utcnow()
    db.flush()
    return contract


def freeze_scope(db: Session, *, tenant_id: uuid.UUID, contract_id: uuid.UUID, baseline: list[dict]) -> Contract:
    """Scope freeze: immutable baseline snapshot + hash (scope-creep guard)."""
    contract = _get_contract(db, tenant_id, contract_id)
    if contract.status not in ("SIGNED", "ACTIVE"):
        raise ConflictError("Scope freeze requires a SIGNED or ACTIVE contract")
    contract.scope_baseline = baseline
    contract.scope_baseline_hash = canonical_payload_hash(baseline)
    contract.scope_frozen_at = utcnow()
    db.flush()
    return contract


def _get_contract(db: Session, tenant_id: uuid.UUID, contract_id: uuid.UUID) -> Contract:
    contract = db.get(Contract, contract_id)
    if contract is None or contract.tenant_id != tenant_id:
        raise NotFoundError("Contract not found")
    return contract


def create_change_request(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    contract_id: uuid.UUID,
    title: str,
    description: str = "",
    quote_amount_minor: int = 0,
    currency: str = "INR",
) -> ChangeRequest:
    """Change request against frozen scope (goes through HITL quote gate)."""
    contract = _get_contract(db, tenant_id, contract_id)
    if not contract.scope_frozen_at:
        raise ConflictError("Change requests require a frozen scope baseline")
    cr = ChangeRequest(
        tenant_id=tenant_id,
        contract_id=contract.id,
        title=title,
        description=description,
        quote_amount_minor=quote_amount_minor,
        currency=currency,
    )
    db.add(cr)
    db.flush()
    return cr


def decide_change_request(
    db: Session, *, tenant_id: uuid.UUID, change_request_id: uuid.UUID, approved: bool
) -> ChangeRequest:
    cr = db.get(ChangeRequest, change_request_id)
    if cr is None or cr.tenant_id != tenant_id:
        raise NotFoundError("Change request not found")
    if cr.status not in ("DRAFT", "QUOTED"):
        raise ConflictError(f"Change request already {cr.status}")
    cr.status = "APPROVED" if approved else "REJECTED"
    cr.decided_at = utcnow()
    db.flush()
    return cr


def create_milestone_invoices(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    contract_id: uuid.UUID,
    project_id: uuid.UUID | None,
    split: list[int],
    prefix: str,
    tax_mode: str = "NON_GST_EXEMPT",
    sac_code: str = "998314",
) -> list[Invoice]:
    """Generate milestone invoices from the configured payment split (SRS §8.2)."""
    contract = _get_contract(db, tenant_id, contract_id)
    if contract.status not in ("SIGNED", "ACTIVE", "COMPLETED"):
        raise ConflictError("Invoices require a signed contract")
    if not split or sum(split) != 100:
        raise ValidationAppError("payment split must sum to 100")
    existing = db.scalars(
        select(Invoice).where(
            Invoice.tenant_id == tenant_id,
            Invoice.project_id == project_id,
        )
    ).all()
    if existing:
        raise ConflictError("Invoices already generated for this project")
    invoices: list[Invoice] = []
    for idx, pct in enumerate(split, start=1):
        invoice = Invoice(
            tenant_id=tenant_id,
            client_id=contract.client_id,
            project_id=project_id,
            number=f"{prefix}{len(existing) + idx:04d}",
            currency=contract.currency,
            amount_minor=int(contract.amount_minor * pct / 100),
            tax_mode=tax_mode,
            sac_code=sac_code,
            status="DRAFT",
            due_date=utcnow() + timedelta(days=15 * idx),
        )
        db.add(invoice)
        invoices.append(invoice)
    db.flush()
    return invoices


def issue_invoice(db: Session, *, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
    invoice = _get_invoice(db, tenant_id, invoice_id)
    if invoice.status != "DRAFT":
        raise ConflictError(f"Cannot issue invoice in status {invoice.status}")
    invoice.status = "ISSUED"
    invoice.issued_at = utcnow()
    db.flush()
    return invoice


def _get_invoice(db: Session, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or invoice.tenant_id != tenant_id:
        raise NotFoundError("Invoice not found")
    return invoice


def record_payment(
    db: Session,
    *,
    principal: Principal,
    invoice_id: uuid.UUID,
    amount_minor: int,
    method: str = "BANK_TRANSFER",
    reference: str = "",
    notes: str = "",
) -> Payment:
    """Manual payment recording — reconciliation is a separate human step."""
    invoice = _get_invoice(db, principal.tenant_id, invoice_id)
    if invoice.status not in ("ISSUED", "PARTIALLY_PAID", "OVERDUE"):
        raise ConflictError(f"Cannot record payment against {invoice.status} invoice")
    if amount_minor <= 0:
        raise ValidationAppError("amount_minor must be positive")
    payment = Payment(
        tenant_id=principal.tenant_id,
        invoice_id=invoice.id,
        amount_minor=amount_minor,
        currency=invoice.currency,
        method=method,
        reference=reference,
        notes=notes,
    )
    db.add(payment)
    db.flush()
    return payment


def reconcile_payment(
    db: Session, *, principal: Principal, payment_id: uuid.UUID, accept: bool
) -> Payment:
    """Founder reconciles a recorded payment against the invoice."""
    payment = db.get(Payment, payment_id)
    if payment is None or payment.tenant_id != principal.tenant_id:
        raise NotFoundError("Payment not found")
    if payment.status != "RECORDED":
        raise ConflictError(f"Payment already {payment.status}")
    if not accept:
        payment.status = "REJECTED"
        db.flush()
        return payment
    payment.status = "RECONCILED"
    payment.reconciled_at = utcnow()
    payment.reconciled_by = principal.user_id
    invoice = db.get(Invoice, payment.invoice_id)
    assert invoice is not None
    invoice.paid_amount_minor += payment.amount_minor
    if invoice.paid_amount_minor >= invoice.amount_minor:
        invoice.status = "PAID"
    else:
        invoice.status = "PARTIALLY_PAID"
    db.flush()
    return payment


def list_invoices(db: Session, tenant_id: uuid.UUID, client_id: uuid.UUID | None = None) -> list[Invoice]:
    stmt = select(Invoice).where(Invoice.tenant_id == tenant_id)
    if client_id:
        stmt = stmt.where(Invoice.client_id == client_id)
    return list(db.scalars(stmt.order_by(Invoice.created_at.desc())))
