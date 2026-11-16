"""Credential hub service: encrypt, resolve, manage, test (docs/34, T-027)."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.security import utcnow
from app.modules.governance.service import record_audit
from app.modules.identity.service import Principal

from .models import IntegrationCredential

PROVIDER_TYPES = ("LLM", "EMAIL", "MESSAGING", "TRANSCRIPTION", "VCS", "GENERIC")
STATUSES = ("DRAFT", "ACTIVE", "INACTIVE", "FAILED")

# provider_key -> settings attribute for the env fallback (disaster recovery)
_ENV_FALLBACK = {
    "groq": "groq_api_keys",
    "gemini": "gemini_api_keys",
    "github_models": "github_models_token",
    "cloudflare_workers_ai": "cloudflare_api_token",
    "openrouter": "openrouter_api_key",
    "mistral": "mistral_api_key",
    "indictrans2": "indictrans2_api_key",
}


def _fernet(settings: Settings) -> Fernet:
    """Derive a stable Fernet key from SECRET_KEY (no extra env var needed).

    sha256 keeps it exactly 32 bytes for Fernet regardless of SECRET_KEY
    length; the same derivation must be used for encrypt and decrypt, so it
    lives here and nowhere else.
    """
    digest = hashlib.sha256(
        settings.secret_key.get_secret_value().encode()
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt(settings: Settings, payload: dict) -> str:
    return _fernet(settings).encrypt(json.dumps(payload).encode()).decode()


def _decrypt(settings: Settings, blob: str) -> dict:
    try:
        return json.loads(_fernet(settings).decrypt(blob.encode()))
    except (InvalidToken, json.JSONDecodeError) as exc:
        raise ConflictError("credential payload cannot be decrypted — "
                            "was SECRET_KEY changed?") from exc


# --------------------------------------------------------------- mutations

def save_credential(
    db: Session,
    *,
    principal: Principal,
    provider_key: str,
    provider_type: str,
    name: str = "",
    secrets: dict | None = None,
    config: dict | None = None,
) -> IntegrationCredential:
    """Create or update the (tenant, provider_key) credential.

    Secrets are write-only from the UI's perspective: passing an empty
    secrets dict on update keeps the existing encrypted payload (so an admin
    can edit config without re-entering the key).
    """
    provider_key = provider_key.strip().lower()
    if not provider_key:
        raise ValidationAppError("provider_key is required")
    if provider_type not in PROVIDER_TYPES:
        raise ValidationAppError(f"provider_type must be one of {PROVIDER_TYPES}")
    row = db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == principal.tenant_id,
            IntegrationCredential.provider_key == provider_key,
        )
    )
    settings = Settings()
    if row is None:
        if not secrets:
            raise ValidationAppError("secrets are required for a new credential")
        row = IntegrationCredential(
            tenant_id=principal.tenant_id,
            provider_key=provider_key,
            provider_type=provider_type,
            name=name or provider_key,
            status="DRAFT",
        )
        row.payload_encrypted = _encrypt(settings, secrets)
        db.add(row)
        action = "integration.created"
    else:
        row.provider_type = provider_type
        row.name = name or provider_key
        if secrets:
            row.payload_encrypted = _encrypt(settings, secrets)
        action = "integration.updated"
    row.config = config or {}
    db.flush()
    record_audit(
        db, tenant_id=principal.tenant_id, actor_type="USER",
        actor_id=str(principal.user_id), action=action,
        resource_type="integration_credential", resource_id=str(row.id),
        payload={"provider_key": provider_key, "provider_type": provider_type,
                 "secrets_rotated": bool(secrets)},
    )
    return row


def set_status(
    db: Session, *, principal: Principal, credential_id: uuid.UUID, status: str
) -> IntegrationCredential:
    if status not in STATUSES:
        raise ValidationAppError(f"status must be one of {STATUSES}")
    row = db.get(IntegrationCredential, credential_id)
    if row is None or row.tenant_id != principal.tenant_id:
        raise NotFoundError("credential not found")
    row.status = status
    db.flush()
    record_audit(
        db, tenant_id=principal.tenant_id, actor_type="USER",
        actor_id=str(principal.user_id), action="integration.status_changed",
        resource_type="integration_credential", resource_id=str(row.id),
        payload={"provider_key": row.provider_key, "to": status},
    )
    return row


def delete_credential(
    db: Session, *, principal: Principal, credential_id: uuid.UUID
) -> None:
    row = db.get(IntegrationCredential, credential_id)
    if row is None or row.tenant_id != principal.tenant_id:
        raise NotFoundError("credential not found")
    record_audit(
        db, tenant_id=principal.tenant_id, actor_type="USER",
        actor_id=str(principal.user_id), action="integration.deleted",
        resource_type="integration_credential", resource_id=str(row.id),
        payload={"provider_key": row.provider_key},
    )
    db.delete(row)
    db.flush()


# --------------------------------------------------------------- resolution

def resolve_secrets(
    db: Session, tenant_id: uuid.UUID, provider_key: str
) -> dict | None:
    """Decrypted secrets of the ACTIVE credential, or None.

    None = no active DB credential; callers fall back to env (the seed).
    INACTIVE / DRAFT / FAILED rows are never resolved — a deactivated
    credential must actually switch the provider off, not silently
    fall through to env (fail-closed intent of the admin action).
    """
    row = db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant_id,
            IntegrationCredential.provider_key == provider_key.strip().lower(),
            IntegrationCredential.status == "ACTIVE",
        )
    )
    if row is None or not row.payload_encrypted:
        return None
    return _decrypt(Settings(), row.payload_encrypted)


def resolve_llm_key(db: Session, tenant_id: uuid.UUID, provider: str,
                    settings: Settings) -> str:
    """DB-first key for an LLM provider, env fallback (docs/34 §2.1).

    Honors both {"api_key": "..."} and {"api_keys": "k1,k2"} payload shapes
    so an admin can move the whole env key pool into the DB unchanged.
    """
    secrets = resolve_secrets(db, tenant_id, provider)
    if secrets:
        pool = secrets.get("api_keys") or secrets.get("api_key") or ""
        first = pool.split(",")[0].strip()
        if first:
            return first
    # env fallback — disaster-recovery seed, not the primary store
    raw = getattr(settings, _ENV_FALLBACK.get(provider, ""), None)
    secret = raw.get_secret_value() if raw is not None else ""
    return secret.split(",")[0].strip() if secret else ""


# ------------------------------------------------------------------- tests

def _models_url(provider: str) -> tuple[str, dict] | None:
    """(url, headers builder) for the provider's cheap key-validity probe."""
    if provider == "gemini":
        return ("https://generativelanguage.googleapis.com/v1beta/models",
                lambda k: {"x-goog-api-key": k})
    if provider == "groq":
        return ("https://api.groq.com/openai/v1/models",
                lambda k: {"Authorization": f"Bearer {k}"})
    if provider == "openrouter":
        return ("https://openrouter.ai/api/v1/models",
                lambda k: {"Authorization": f"Bearer {k}"})
    if provider == "mistral":
        return ("https://api.mistral.ai/v1/models",
                lambda k: {"Authorization": f"Bearer {k}"})
    return None


def test_credential(
    db: Session, *, principal: Principal, credential_id: uuid.UUID
) -> IntegrationCredential:
    """Live-test the credential with the cheapest call its provider offers.

    Stores the verdict on the row (never the key itself) and audits it.
    A failed test moves an ACTIVE row to FAILED so a bad rotation stops
    being used by resolution immediately.
    """
    row = db.get(IntegrationCredential, credential_id)
    if row is None or row.tenant_id != principal.tenant_id:
        raise NotFoundError("credential not found")
    secrets = _decrypt(Settings(), row.payload_encrypted)
    verdict = {"ok": False, "detail": "", "tested_at": utcnow().isoformat()}
    try:
        if row.provider_type == "LLM" and _models_url(row.provider_key):
            url, headers = _models_url(row.provider_key)
            key = (secrets.get("api_keys") or secrets.get("api_key") or "").split(",")[0].strip()
            with httpx.Client(timeout=15) as client:
                resp = client.get(url, headers=headers(key))
            verdict["ok"] = resp.status_code == 200
            verdict["detail"] = (f"{resp.status_code}: "
                                 + ("key valid, models listed" if resp.status_code == 200
                                    else resp.text[:120]))
        elif row.provider_key == "telegram_bot":
            token = secrets.get("bot_token", "")
            with httpx.Client(timeout=15) as client:
                resp = client.get(
                    f"https://api.telegram.org/bot{token}/getMe")
            verdict["ok"] = resp.status_code == 200 and resp.json().get("ok")
            verdict["detail"] = (f"bot @{resp.json().get('result', {}).get('username', '?')}"
                                 if verdict["ok"] else resp.text[:120])
        else:
            verdict["ok"] = False
            verdict["detail"] = ("no automated test for this provider type yet — "
                                 "use it in a real workflow to verify")
    except httpx.HTTPError as exc:
        verdict["detail"] = f"network error: {exc}"[:200]
    row.last_tested_at = utcnow()
    row.last_test_result = verdict
    if verdict["ok"]:
        if row.status in ("DRAFT", "FAILED"):
            row.status = "ACTIVE"  # a passing test is the activation gate
    elif row.status == "ACTIVE":
        row.status = "FAILED"
    db.flush()
    record_audit(
        db, tenant_id=principal.tenant_id, actor_type="USER",
        actor_id=str(principal.user_id), action="integration.tested",
        resource_type="integration_credential", resource_id=str(row.id),
        payload={"provider_key": row.provider_key, "ok": verdict["ok"]},
    )
    return row


def masked_hint(row: IntegrationCredential) -> str:
    """Non-secret display hint (UI must never render the payload back)."""
    try:
        secrets = _decrypt(Settings(), row.payload_encrypted)
    except ConflictError:
        return "undecryptable"
    pool = secrets.get("api_keys") or secrets.get("api_key") or secrets.get(
        "bot_token") or secrets.get("app_password") or ""
    first = pool.split(",")[0].strip()
    if not first:
        return "(empty)"
    if len(first) <= 6:
        return "*" * len(first)
    return f"{first[:3]}…{first[-3:]} ({len(first)} chars)"
