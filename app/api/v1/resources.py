"""Resource/quota API: providers, products, snapshots, admission test."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CsrfDep, CurrentPrincipal, DbDep, WritePrincipal
from app.core.enums import BillingState, ProviderCategory, QuotaConfidence
from app.modules.resources import service as quota

router = APIRouter(prefix="/providers", tags=["resources"])


class ProviderAccountCreate(BaseModel):
    provider: str
    account_ref: str = "default"
    display_name: str = ""
    plan: str = "FREE"
    billing_state: BillingState = BillingState.FREE_UNVERIFIED
    region: str = ""
    secret_ref: str = ""
    enabled: bool = False


class ProviderProductCreate(BaseModel):
    account_id: uuid.UUID
    product_key: str
    category: ProviderCategory
    metric_key: str = "requests"
    allowance: int = Field(ge=0)
    unit: str = "count"
    is_paid: bool = False
    enabled: bool = True


class SnapshotCreate(BaseModel):
    product_id: uuid.UUID
    provider_reported: int | None = None
    locally_metered: int | None = None
    confidence: str = QuotaConfidence.MEDIUM.value


class AdmitTest(BaseModel):
    category: ProviderCategory
    quantity: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8)


class TripBreaker(BaseModel):
    product_id: uuid.UUID
    failure_code: str = "HTTP_429"


def _account_out(a) -> dict:
    return {
        "id": str(a.id), "provider": a.provider, "account_ref": a.account_ref,
        "billing_state": a.billing_state, "plan": a.plan, "enabled": a.enabled,
        "health": a.health, "is_eligible_free": a.is_eligible_free,
    }


def _product_out(p) -> dict:
    return {
        "id": str(p.id), "product_key": p.product_key, "category": p.category,
        "allowance": p.allowance, "unit": p.unit, "is_paid": p.is_paid,
        "enabled": p.enabled, "metric_key": p.metric_key,
    }


@router.get("/accounts")
def list_accounts(db: DbDep, principal: CurrentPrincipal) -> list[dict]:
    from sqlalchemy import select

    from app.modules.resources.models import ProviderAccount

    rows = db.scalars(
        select(ProviderAccount).where(ProviderAccount.tenant_id == principal.tenant_id)
    )
    return [_account_out(a) for a in rows]


@router.post("/accounts", status_code=201)
def create_account(
    body: ProviderAccountCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    account = quota.register_provider_account(
        db, tenant_id=principal.tenant_id, provider=body.provider,
        account_ref=body.account_ref, display_name=body.display_name, plan=body.plan,
        billing_state=body.billing_state.value, region=body.region,
        secret_ref=body.secret_ref, enabled=body.enabled,
    )
    return _account_out(account)


@router.post("/products", status_code=201)
def create_product(
    body: ProviderProductCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    from app.modules.resources.models import ProviderAccount

    account = db.get(ProviderAccount, body.account_id)
    if account is None or account.tenant_id != principal.tenant_id:
        from app.core.errors import NotFoundError

        raise NotFoundError("Provider account not found")
    product = quota.register_provider_product(
        db, account=account, product_key=body.product_key, category=body.category,
        metric_key=body.metric_key, allowance=body.allowance, unit=body.unit,
        is_paid=body.is_paid, enabled=body.enabled,
    )
    return _product_out(product)


@router.get("/products")
def list_products(db: DbDep, principal: CurrentPrincipal) -> list[dict]:
    from sqlalchemy import select

    from app.modules.resources.models import ProviderAccount, ProviderProduct

    rows = db.execute(
        select(ProviderProduct)
        .join(ProviderAccount, ProviderProduct.account_id == ProviderAccount.id)
        .where(ProviderAccount.tenant_id == principal.tenant_id)
    ).scalars()
    return [_product_out(p) for p in rows]


@router.post("/snapshots", status_code=201)
def create_snapshot(
    body: SnapshotCreate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    from app.core.errors import NotFoundError
    from app.modules.resources.models import ProviderAccount, ProviderProduct

    product = db.execute(
        select(ProviderProduct)
        .join(ProviderAccount, ProviderProduct.account_id == ProviderAccount.id)
        .where(ProviderProduct.id == body.product_id, ProviderAccount.tenant_id == principal.tenant_id)
    ).scalar_one_or_none()
    if product is None:
        raise NotFoundError("Provider product not found")
    snapshot = quota.record_snapshot(
        db, product, provider_reported=body.provider_reported,
        locally_metered=body.locally_metered, confidence=body.confidence,
    )
    return {
        "id": str(snapshot.id), "effective_usage": snapshot.effective_usage,
        "allowance": snapshot.allowance, "confidence": snapshot.confidence,
        "observed_at": snapshot.observed_at.isoformat(),
    }


@router.post("/admit")
def admit(body: AdmitTest, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep) -> dict:
    decision = quota.admit_usage(
        db, tenant_id=principal.tenant_id, category=body.category,
        quantity=body.quantity, idempotency_key=body.idempotency_key,
    )
    return {
        "admitted": decision.admitted,
        "provider_product_id": str(decision.provider_product_id) if decision.provider_product_id else None,
        "reservation_id": str(decision.reservation_id) if decision.reservation_id else None,
        "reason": decision.reason,
    }


@router.post("/breakers/trip")
def trip(body: TripBreaker, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep) -> dict:
    from app.core.errors import NotFoundError
    from app.modules.resources.models import ProviderProduct

    product = db.get(ProviderProduct, body.product_id)
    if product is None:
        raise NotFoundError("Provider product not found")
    breaker = quota.trip_circuit(db, product, failure_code=body.failure_code)
    return {"state": breaker.state, "cooldown_until": breaker.cooldown_until.isoformat() if breaker.cooldown_until else None}
