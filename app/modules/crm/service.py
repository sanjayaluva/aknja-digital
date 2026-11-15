"""CRM service: lead qualification, clients, contacts (docs/08 lifecycle)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ClientStatus, LeadStatus
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.modules.crm.models import Client, Contact, Lead
from app.modules.identity.service import Principal

# Allowed lead status transitions (commercial lifecycle, SRS §15).
LEAD_TRANSITIONS: dict[LeadStatus, set[LeadStatus]] = {
    LeadStatus.NEW: {LeadStatus.CONTACTED, LeadStatus.DISQUALIFIED},
    LeadStatus.CONTACTED: {LeadStatus.QUALIFIED, LeadStatus.DISQUALIFIED, LeadStatus.LOST},
    LeadStatus.QUALIFIED: {LeadStatus.DISCOVERY, LeadStatus.DISQUALIFIED, LeadStatus.LOST},
    LeadStatus.DISCOVERY: {LeadStatus.PROPOSAL_SENT, LeadStatus.DISQUALIFIED, LeadStatus.LOST},
    LeadStatus.PROPOSAL_SENT: {LeadStatus.WON, LeadStatus.LOST},
    LeadStatus.WON: set(),
    LeadStatus.LOST: {LeadStatus.CONTACTED},
    LeadStatus.DISQUALIFIED: set(),
}


def create_client(
    db: Session, *, principal: Principal, display_name: str, email: str = "", phone: str = ""
) -> Client:
    client = Client(
        tenant_id=principal.tenant_id,
        display_name=display_name,
        email=email,
        phone=phone,
        status=ClientStatus.PROSPECT.value,
    )
    db.add(client)
    db.flush()
    return client


def get_client(db: Session, tenant_id: uuid.UUID, client_id: uuid.UUID) -> Client:
    client = db.get(Client, client_id)
    if client is None or client.tenant_id != tenant_id:
        raise NotFoundError("Client not found")
    return client


def list_clients(db: Session, tenant_id: uuid.UUID) -> list[Client]:
    return list(
        db.scalars(
            select(Client)
            .where(Client.tenant_id == tenant_id)
            .order_by(Client.created_at.desc())
        )
    )


def create_lead(
    db: Session,
    *,
    principal: Principal,
    title: str,
    source: str = "DIRECT",
    description: str = "",
    contact_email: str = "",
    budget_minor: int = 0,
    currency: str = "INR",
    feasibility_score: int = 0,
) -> Lead:
    if not 0 <= feasibility_score <= 100:
        raise ValidationAppError("feasibility_score must be between 0 and 100")
    lead = Lead(
        tenant_id=principal.tenant_id,
        title=title,
        source=source,
        description=description,
        contact_email=contact_email,
        budget_minor=budget_minor,
        currency=currency,
        feasibility_score=feasibility_score,
    )
    db.add(lead)
    db.flush()
    return lead


def get_lead(db: Session, tenant_id: uuid.UUID, lead_id: uuid.UUID) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None or lead.tenant_id != tenant_id:
        raise NotFoundError("Lead not found")
    return lead


def list_leads(db: Session, tenant_id: uuid.UUID, status: str | None = None) -> list[Lead]:
    stmt = select(Lead).where(Lead.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(Lead.status == status)
    return list(db.scalars(stmt.order_by(Lead.created_at.desc())))


def qualify_lead(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    lead_id: uuid.UUID,
    to_status: LeadStatus,
    feasibility_score: int | None = None,
    notes: str = "",
) -> Lead:
    lead = get_lead(db, tenant_id, lead_id)
    current = LeadStatus(lead.status)
    if to_status not in LEAD_TRANSITIONS.get(current, set()):
        raise ConflictError(
            f"Illegal lead transition {current.value} → {to_status.value}",
            details={"from": current.value, "to": to_status.value},
        )
    # Threshold from system_settings is read by the caller (UI/API layer);
    # the hard floor of qualification sanity is enforced here.
    if to_status == LeadStatus.QUALIFIED and feasibility_score is not None and feasibility_score < 70:
        raise ValidationAppError("Qualification requires feasibility_score >= 70")
    lead.status = to_status.value
    if feasibility_score is not None:
        lead.feasibility_score = feasibility_score
    if notes:
        lead.qualification_notes = notes
    if to_status in (LeadStatus.WON, LeadStatus.LOST, LeadStatus.DISQUALIFIED):
        from app.core.security import utcnow

        lead.decided_at = utcnow()
    db.flush()
    return lead


def convert_lead_to_client(db: Session, *, tenant_id: uuid.UUID, lead_id: uuid.UUID) -> Client:
    """WON lead becomes a client record (with contact carried over)."""
    lead = get_lead(db, tenant_id, lead_id)
    if lead.status != LeadStatus.WON.value:
        raise ConflictError("Only WON leads can be converted to clients")
    client = Client(
        tenant_id=tenant_id,
        display_name=lead.title,
        email=lead.contact_email,
        status=ClientStatus.ACTIVE.value,
        notes=f"Converted from lead {lead.id}",
    )
    db.add(client)
    db.flush()
    lead.client_id = client.id
    db.flush()
    return client


def add_contact(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    client_id: uuid.UUID,
    full_name: str,
    email: str = "",
    phone: str = "",
    role: str = "",
    is_primary: bool = False,
) -> Contact:
    client = get_client(db, tenant_id, client_id)
    contact = Contact(
        tenant_id=tenant_id,
        client_id=client.id,
        full_name=full_name,
        email=email,
        phone=phone,
        role=role,
        is_primary=is_primary,
    )
    db.add(contact)
    db.flush()
    return contact
