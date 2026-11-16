"""CRM API: leads, clients, contacts."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CsrfDep, CurrentPrincipal, DbDep, WritePrincipal
from app.core.enums import ClientStatus, LeadStatus
from app.modules.crm import service as crm
from app.modules.governance.service import record_audit

router = APIRouter(tags=["crm"])


class LeadCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    source: str = "DIRECT"
    description: str = ""
    contact_email: EmailStr | None = None
    budget_minor: int = Field(default=0, ge=0)
    currency: str = "INR"
    feasibility_score: int = Field(default=0, ge=0, le=100)


class LeadQualify(BaseModel):
    to_status: LeadStatus
    feasibility_score: int | None = Field(default=None, ge=0, le=100)
    notes: str = ""


class ClientCreate(BaseModel):
    display_name: str = Field(min_length=2, max_length=200)
    email: EmailStr | None = None
    phone: str = ""


class ContactCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr | None = None
    phone: str = ""
    role: str = ""
    is_primary: bool = False


def _lead_out(lead) -> dict:
    return {
        "id": str(lead.id),
        "title": lead.title,
        "source": lead.source,
        "status": lead.status,
        "feasibility_score": lead.feasibility_score,
        "budget_minor": lead.budget_minor,
        "currency": lead.currency,
        "client_id": str(lead.client_id) if lead.client_id else None,
        "created_at": lead.created_at.isoformat(),
    }


def _client_out(client) -> dict:
    return {
        "id": str(client.id),
        "display_name": client.display_name,
        "status": client.status,
        "email": client.email,
        "phone": client.phone,
        "created_at": client.created_at.isoformat(),
    }


@router.get("/leads")
def list_leads(
    db: DbDep, principal: CurrentPrincipal, status: str | None = None
) -> list[dict]:
    return [_lead_out(l) for l in crm.list_leads(db, principal.tenant_id, status)]


@router.post("/leads", status_code=201)
def create_lead(body: LeadCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep) -> dict:
    lead = crm.create_lead(
        db,
        principal=principal,
        title=body.title,
        source=body.source,
        description=body.description,
        contact_email=str(body.contact_email or ""),
        budget_minor=body.budget_minor,
        currency=body.currency,
        feasibility_score=body.feasibility_score,
    )
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        actor_type="USER",
        actor_id=str(principal.user_id),
        action="lead.created",
        resource_type="lead",
        resource_id=str(lead.id),
    )
    return _lead_out(lead)


@router.post("/leads/{lead_id}/qualify")
def qualify_lead(
    lead_id: uuid.UUID, body: LeadQualify, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    lead = crm.qualify_lead(
        db,
        tenant_id=principal.tenant_id,
        lead_id=lead_id,
        to_status=body.to_status,
        feasibility_score=body.feasibility_score,
        notes=body.notes,
    )
    return _lead_out(lead)


@router.post("/leads/{lead_id}/convert", status_code=201)
def convert_lead(
    lead_id: uuid.UUID, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    client = crm.convert_lead_to_client(db, tenant_id=principal.tenant_id, lead_id=lead_id)
    return _client_out(client)


@router.get("/clients")
def list_clients(db: DbDep, principal: CurrentPrincipal) -> list[dict]:
    return [_client_out(c) for c in crm.list_clients(db, principal.tenant_id)]


@router.post("/clients", status_code=201)
def create_client(body: ClientCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep) -> dict:
    client = crm.create_client(
        db,
        principal=principal,
        display_name=body.display_name,
        email=str(body.email or ""),
        phone=body.phone,
    )
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        actor_type="USER",
        actor_id=str(principal.user_id),
        action="client.created",
        resource_type="client",
        resource_id=str(client.id),
    )
    return _client_out(client)


@router.get("/clients/{client_id}")
def get_client(client_id: uuid.UUID, db: DbDep, principal: CurrentPrincipal) -> dict:
    client = crm.get_client(db, principal.tenant_id, client_id)
    return _client_out(client)


@router.post("/clients/{client_id}/contacts", status_code=201)
def add_contact(
    client_id: uuid.UUID, body: ContactCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    contact = crm.add_contact(
        db,
        tenant_id=principal.tenant_id,
        client_id=client_id,
        full_name=body.full_name,
        email=str(body.email or ""),
        phone=body.phone,
        role=body.role,
        is_primary=body.is_primary,
    )
    return {"id": str(contact.id), "full_name": contact.full_name, "is_primary": contact.is_primary}


@router.post("/clients/{client_id}/status")
def set_client_status(
    client_id: uuid.UUID,
    db: DbDep,
    principal: WritePrincipal,
    _csrf: CsrfDep,
    status: ClientStatus = Query(...),  # noqa: B008
) -> dict:
    client = crm.get_client(db, principal.tenant_id, client_id)
    client.status = status.value
    db.flush()
    return _client_out(client)
