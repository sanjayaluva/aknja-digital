"""Maintenance mode: controlled write freeze (v5.3.2 §5A, v5.3.1 L141).

When enabled the application serves read-only: every mutating HTTP request
(PATCH/POST/PUT/DELETE) except authentication gets 503 + Retry-After; reads
and /healthz keep working so monitoring and the admin console stay visible.
Activation/deactivation is audited and notifies the founder via the Telegram
outbox. The flag is read from the database with a short TTL cache (not the
process-local settings cache) so a CLI toggle in another process takes
effect within ``_TTL_SECONDS``.
"""

from __future__ import annotations

import threading
import time
import uuid

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.security import utcnow
from app.modules.governance.service import record_audit
from app.modules.ops.notifications import notify_admin
from app.modules.ops.settings_service import invalidate_cache

MAINTENANCE_ENABLED_KEY = "maintenance_mode_enabled"
MAINTENANCE_REASON_KEY = "maintenance_reason"

# Auth must stay usable during a freeze (operators log in to watch state);
# everything else mutating is blocked.
_EXEMPT_MUTATING_PATHS = {"/api/v1/auth/login", "/api/v1/auth/logout"}

_TTL_SECONDS = 5.0
_ttl_lock = threading.Lock()
_ttl_cached_at = 0.0
_ttl_cached_value = False


def set_maintenance_mode(
    db: Session, *, enabled: bool, reason: str = "", actor: str = "SYSTEM"
) -> tuple[bool, bool]:
    """Set the write-freeze flag. Returns (changed, previous_state).

    Upserts the settings rows directly (a CLI/system actor has no principal);
    audits the transition and notifies the founder exactly once per state
    change. No-op (no audit, no notification) when already in the state.
    """
    from app.modules.ops.models import SystemSetting

    current = db.get(SystemSetting, MAINTENANCE_ENABLED_KEY)
    previous = bool(current.value_json) if current else False
    if current is not None and previous == enabled:
        return False, previous

    for key, value in ((MAINTENANCE_ENABLED_KEY, enabled), (MAINTENANCE_REASON_KEY, reason)):
        row = db.get(SystemSetting, key)
        if row is None:  # unseeded deployment: create on demand
            db.add(SystemSetting(key=key, category="ops_recovery", value_json=value,
                                 value_type="bool" if key == MAINTENANCE_ENABLED_KEY else "string",
                                 description="maintenance mode"))
        else:
            row.value_json = value
    db.flush()

    tenant_row = db.execute(text(
        "SELECT id FROM tenants ORDER BY created_at LIMIT 1")).scalar_one_or_none()
    record_audit(
        db,
        tenant_id=tenant_row,
        actor_type="SYSTEM",
        actor_id=actor,
        action="maintenance.enabled" if enabled else "maintenance.disabled",
        resource_type="system_setting",
        resource_id=MAINTENANCE_ENABLED_KEY,
        payload={"reason": reason},
    )
    if tenant_row is not None:
        notify_admin(
            db,
            template_key="maintenance.activated" if enabled else "maintenance.deactivated",
            payload={"reason": reason or ("controlled promotion window" if enabled else "normal operation")},
            idempotency_key=f"maintenance.{'on' if enabled else 'off'}:{utcnow():%Y%m%d%H%M%S}",
            tenant_id=tenant_row,
        )
    db.commit()
    invalidate_cache()
    _clear_ttl_cache()
    return True, previous


def is_maintenance_enabled() -> bool:
    """Current write-freeze state, TTL-cached, read straight from the DB.

    Deliberately bypasses the settings cache: that cache is process-local
    and would never see a CLI toggle from another process.
    """
    global _ttl_cached_at, _ttl_cached_value
    now = time.monotonic()
    with _ttl_lock:
        if now - _ttl_cached_at < _TTL_SECONDS:
            return _ttl_cached_value
    value = _read_flag_from_db()
    with _ttl_lock:
        _ttl_cached_at = now
        _ttl_cached_value = value
    return value


def _read_flag_from_db() -> bool:
    from app.core.db import get_session_local
    from app.modules.ops.models import SystemSetting

    session = get_session_local()()
    try:
        row = session.get(SystemSetting, MAINTENANCE_ENABLED_KEY)
        return bool(row.value_json) if row else False
    except Exception:  # noqa: BLE001 — fail-open: a DB blip must not freeze reads
        return False
    finally:
        session.close()


def _clear_ttl_cache() -> None:
    global _ttl_cached_at
    with _ttl_lock:
        _ttl_cached_at = 0.0


def maintenance_reason() -> str:
    from app.core.db import get_session_local
    from app.modules.ops.models import SystemSetting

    session = get_session_local()()
    try:
        row = session.get(SystemSetting, MAINTENANCE_REASON_KEY)
        return str(row.value_json) if row else ""
    finally:
        session.close()


class MaintenanceModeMiddleware(BaseHTTPMiddleware):
    """503 + Retry-After for mutating requests while the freeze is on."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)
        if request.url.path in _EXEMPT_MUTATING_PATHS:
            return await call_next(request)
        if not is_maintenance_enabled():
            return await call_next(request)
        reason = maintenance_reason() or "scheduled maintenance"
        request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:16])
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "MAINTENANCE_MODE",
                    "message": f"The system is in maintenance mode ({reason}). "
                    "Writes are temporarily frozen; reads remain available.",
                    "request_id": request_id,
                }
            },
            headers={"Retry-After": "30"},
        )
