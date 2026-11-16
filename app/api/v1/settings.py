"""Admin settings API (zero-hardcode system_settings engine)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CsrfDep, CurrentPrincipal, DbDep, WritePrincipal
from app.modules.ops import settings_service

router = APIRouter(prefix="/admin/settings", tags=["settings"])


class SettingUpdate(BaseModel):
    key: str
    value: Any


@router.get("")
def list_settings(db: DbDep, principal: CurrentPrincipal) -> list[dict]:
    return [
        {
            "key": s.key, "category": s.category, "value": s.value_json,
            "value_type": s.value_type, "description": s.description,
        }
        for s in settings_service.get_all_settings(db)
    ]


@router.put("")
def update_setting(
    body: SettingUpdate, db: DbDep, principal: WritePrincipal, _csrf: CsrfDep
) -> dict:
    setting = settings_service.update_setting(
        db, principal=principal, key=body.key, value=body.value
    )
    return {"key": setting.key, "value": setting.value_json}
