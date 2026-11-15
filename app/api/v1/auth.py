"""Authentication API: login, logout, session introspection."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, ValidationError

from app.api.deps import SESSION_COOKIE, CurrentPrincipal, DbDep
from app.core.config import get_settings
from app.modules.governance.service import record_audit
from app.modules.identity import service as identity

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class SessionInfo(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: str
    tenant_id: uuid.UUID
    csrf_token: str


async def _login_body(request: Request) -> LoginRequest:
    """Accept BOTH JSON (API clients) and urlencoded bodies (the htmx login
    form serializes form fields as application/x-www-form-urlencoded — a
    JSON-only signature broke every real-browser login; found by E2E T-007).
    """
    ctype = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
        data = dict(await request.form())
    else:
        data = await request.json()
    try:
        return LoginRequest.model_validate(data)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(), body=data) from exc


@router.post("/login")
def login(
    request: Request, db: DbDep, body: Annotated[LoginRequest, Depends(_login_body)]
) -> JSONResponse:
    user = identity.authenticate(db, email=body.email, password=body.password)
    token, session = identity.create_session(
        db,
        user,
        ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    principal = identity.resolve_principal(db, token)
    assert principal is not None
    record_audit(
        db,
        tenant_id=None,
        actor_type="USER",
        actor_id=str(user.id),
        action="auth.login",
        resource_type="user_session",
        resource_id=str(session.id),
    )
    settings = get_settings()
    payload = SessionInfo(
        user_id=principal.user_id,
        email=principal.email,
        full_name=principal.full_name,
        role=principal.role.value,
        tenant_id=principal.tenant_id,
        csrf_token=principal.csrf_token,
    ).model_dump(mode="json")
    resp = JSONResponse(payload)
    resp.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
    )
    return resp


@router.post("/logout")
def logout(db: DbDep, principal: CurrentPrincipal) -> JSONResponse:
    identity.revoke_session(db, principal.session_id)
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        actor_type="USER",
        actor_id=str(principal.user_id),
        action="auth.logout",
        resource_type="user_session",
        resource_id=str(principal.session_id),
    )
    resp = JSONResponse({"status": "logged_out"})
    resp.delete_cookie(SESSION_COOKIE)
    # htmx honour redirect: without this the browser stays on the (now stale)
    # console page after sign-out — found by real-browser E2E (T-007)
    resp.headers["HX-Redirect"] = "/login"
    return resp


@router.get("/session")
def whoami(principal: CurrentPrincipal) -> SessionInfo:
    return SessionInfo(
        user_id=principal.user_id,
        email=principal.email,
        full_name=principal.full_name,
        role=principal.role.value,
        tenant_id=principal.tenant_id,
        csrf_token=principal.csrf_token,
    )
