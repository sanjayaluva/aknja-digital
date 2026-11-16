"""FastAPI dependencies: DB session, authentication, CSRF and RBAC guards."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.db import get_session_local
from app.core.enums import UserRole
from app.core.errors import AuthenticationError, AuthorizationError
from app.core.security import constant_time_equals
from app.modules.identity.service import Principal, resolve_principal

SESSION_COOKIE = "aknja_session"
CSRF_HEADER = "x-csrf-token"


def get_db() -> Session:
    db = get_session_local()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


DbDep = Annotated[Session, Depends(get_db)]


def get_principal(
    db: DbDep,
    request: Request,
    aknja_session: Annotated[str | None, Cookie()] = None,
) -> Principal | None:
    if aknja_session is None:
        return None
    principal = resolve_principal(db, aknja_session)
    if principal is None:
        return None
    request.state.principal = principal
    return principal


OptionalPrincipal = Annotated[Principal | None, Depends(get_principal)]


def require_principal(principal: OptionalPrincipal) -> Principal:
    if principal is None:
        raise AuthenticationError("Authentication required")
    return principal


CurrentPrincipal = Annotated[Principal, Depends(require_principal)]


def require_write(principal: CurrentPrincipal) -> Principal:
    """Mutating API routes require a write-capable role (deny by default)."""
    if not principal.can_write:
        raise AuthorizationError(
            "Role is read-only for this operation",
            details={"role": principal.role.value},
        )
    return principal


WritePrincipal = Annotated[Principal, Depends(require_write)]


def require_roles(*roles: UserRole):
    """Dependency factory enforcing role membership (deny by default)."""

    def _checker(principal: CurrentPrincipal) -> Principal:
        if principal.role not in roles:
            raise AuthorizationError(
                "Insufficient role for this operation",
                details={"required": [r.value for r in roles], "have": principal.role.value},
            )
        return principal

    return Depends(_checker)


def verify_csrf(
    principal: CurrentPrincipal,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> None:
    """Double-submit CSRF check for cookie-authenticated mutations."""
    if x_csrf_token is None:
        raise AuthenticationError("CSRF token header missing")
    if not constant_time_equals(x_csrf_token, principal.csrf_token):
        raise AuthorizationError("CSRF token mismatch")


CsrfDep = Annotated[None, Depends(verify_csrf)]
