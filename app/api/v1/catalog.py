"""Service catalog API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CsrfDep, CurrentPrincipal, DbDep, WritePrincipal
from app.modules.catalog import service as catalog
from app.modules.catalog.models import ServiceCategory

router = APIRouter(prefix="/services", tags=["catalog"])


class ServiceUpdate(BaseModel):
    availability: str | None = None
    readiness: str | None = None
    execution_mode: str | None = None
    sellable: bool | None = None


def _service_out(s) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "description": s.description,
        "availability": s.availability,
        "readiness": s.readiness,
        "execution_mode": s.execution_mode,
        "sellable": s.sellable,
        "is_sellable_now": s.is_sellable_now,
    }


@router.get("")
def list_services(
    db: DbDep,
    principal: CurrentPrincipal,
    search: str = "",
    readiness: str = "",
    availability: str = "",
    limit: int = 100,
) -> list[dict]:
    return [
        _service_out(s)
        for s in catalog.list_services(
            db, principal.tenant_id, search=search, readiness=readiness, availability=availability, limit=limit
        )
    ]


@router.get("/{service_id}")
def get_service(service_id: uuid.UUID, db: DbDep, principal: CurrentPrincipal) -> dict:
    return _service_out(catalog.get_service(db, principal.tenant_id, service_id))


@router.patch("/{service_id}")
def update_service(
    service_id: uuid.UUID, body: ServiceUpdate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    service = catalog.update_service_lifecycle(
        db,
        principal=principal,
        service_id=service_id,
        availability=body.availability,
        readiness=body.readiness,
        execution_mode=body.execution_mode,
        sellable=body.sellable,
    )
    return _service_out(service)


@router.get("/tree/all")
def catalog_tree(db: DbDep, principal: CurrentPrincipal) -> list[dict]:
    """Category → subcategory → service tree for the tenant."""
    from sqlalchemy import select

    from app.modules.catalog.models import Service, ServiceSubcategory

    categories = db.scalars(
        select(ServiceCategory)
        .where(ServiceCategory.tenant_id == principal.tenant_id)
        .order_by(ServiceCategory.sort_order)
    ).all()
    result = []
    for category in categories:
        subcats = db.scalars(
            select(ServiceSubcategory)
            .where(ServiceSubcategory.category_id == category.id)
            .order_by(ServiceSubcategory.sort_order)
        ).all()
        subs = []
        for sub in subcats:
            services = db.scalars(
                select(Service)
                .where(Service.subcategory_id == sub.id)
                .order_by(Service.sort_order, Service.name)
            ).all()
            subs.append(
                {
                    "id": str(sub.id),
                    "code": sub.code,
                    "name": sub.name,
                    "services": [_service_out(s) for s in services],
                }
            )
        result.append(
            {
                "id": str(category.id),
                "domain": category.domain,
                "code": category.code,
                "name": category.name,
                "subcategories": subs,
            }
        )
    return result
