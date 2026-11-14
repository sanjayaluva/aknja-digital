"""Identity service: registration of bootstrap data, authentication,
session lifecycle and role checks.

Authorization model (SRS §6): deny-by-default. Every request carries an
authenticated principal with a tenant scope; portal users are additionally
bound to a single client record via their membership row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import UserRole
from app.core.errors import AuthenticationError, AuthorizationError, ConflictError
from app.core.security import (
    generate_token,
    hash_password,
    hash_token,
    new_csrf_token,
    utcnow,
    verify_password,
)
from app.modules.identity.models import Tenant, TenantMembership, User, UserSession

MAX_FAILED_LOGINS = 10
LOCKOUT_MINUTES = 15

# Roles allowed to use the internal operations interface.
INTERNAL_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.INTERNAL_OPERATOR,
    UserRole.PARTNER_OPERATOR,
    UserRole.READ_ONLY_AUDITOR,
}
# Roles allowed to approve HITL gates (humans only, never SYSTEM_WORKER).
APPROVER_ROLES = {UserRole.SUPER_ADMIN, UserRole.INTERNAL_OPERATOR}
WRITE_ROLES = {UserRole.SUPER_ADMIN, UserRole.INTERNAL_OPERATOR, UserRole.PARTNER_OPERATOR}
PORTAL_ROLES = {UserRole.CLIENT_OWNER, UserRole.CLIENT_MEMBER}


@dataclass
class Principal:
    """Authenticated request context — the ONLY source of tenant scope."""

    user_id: uuid.UUID
    email: str
    tenant_id: uuid.UUID
    role: UserRole
    client_id: uuid.UUID | None  # portal users only
    session_id: uuid.UUID
    csrf_token: str
    full_name: str = ""

    @property
    def is_super_admin(self) -> bool:
        return self.role == UserRole.SUPER_ADMIN

    @property
    def is_internal(self) -> bool:
        return self.role in INTERNAL_ROLES

    @property
    def is_portal(self) -> bool:
        return self.role in PORTAL_ROLES

    @property
    def can_write(self) -> bool:
        return self.role in WRITE_ROLES

    @property
    def can_approve(self) -> bool:
        return self.role in APPROVER_ROLES


def bootstrap_internal_tenant(db: Session, name: str = "Aknja Digital") -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.slug == "aknja-internal"))
    if tenant is None:
        tenant = Tenant(name=name, slug="aknja-internal")
        db.add(tenant)
        db.flush()
    return tenant


def create_user(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str = "",
    tenant_id: uuid.UUID,
    role: UserRole,
    client_id: uuid.UUID | None = None,
) -> User:
    email = email.strip().lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ConflictError(f"User with email {email} already exists")
    user = User(email=email, full_name=full_name, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    db.add(TenantMembership(tenant_id=tenant_id, user_id=user.id, role=role.value, client_id=client_id))
    db.flush()
    return user


def authenticate(db: Session, *, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        # Burn comparable time to avoid user-enumeration timing signal.
        verify_password("$argon2id$v=19$m=65536,t=3,p=4$dummy$dummy", password)
        raise AuthenticationError("Invalid email or password")
    if not user.is_active or user.is_locked:
        raise AuthenticationError("Account is locked or disabled")
    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
        # Commit immediately: the request will raise, and the counter must
        # survive the request-scoped rollback.
        db.commit()
        raise AuthenticationError("Invalid email or password")
    user.failed_login_count = 0
    user.locked_until = None
    db.flush()
    return user


def create_session(
    db: Session, user: User, *, ip: str = "", user_agent: str = ""
) -> tuple[str, UserSession]:
    settings = get_settings()
    token = generate_token("sess_")
    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=new_csrf_token(),
        ip_address=ip[:64],
        user_agent=user_agent[:256],
        expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(session)
    db.flush()
    return token, session


def resolve_principal(db: Session, token: str) -> Principal | None:
    """Resolve a session token to a Principal (tenant scope from membership)."""
    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    )
    if session is None or not session.is_valid:
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    membership = db.scalar(
        select(TenantMembership).where(TenantMembership.user_id == user.id)
    )
    if membership is None:
        return None
    tenant = db.get(Tenant, membership.tenant_id)
    if tenant is None or not tenant.is_active:
        return None
    return Principal(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        tenant_id=membership.tenant_id,
        role=UserRole(membership.role),
        client_id=membership.client_id,
        session_id=session.id,
        csrf_token=session.csrf_token,
    )


def revoke_session(db: Session, session_id: uuid.UUID) -> None:
    session = db.get(UserSession, session_id)
    if session is not None and session.revoked_at is None:
        session.revoked_at = utcnow()
        db.flush()


def require_role(principal: Principal, *roles: UserRole) -> None:
    if principal.role not in roles:
        raise AuthorizationError(
            "Insufficient role for this operation",
            details={"required": [r.value for r in roles], "have": principal.role.value},
        )
