"""Security primitives: password hashing (argon2id), token generation, CSRF.

API keys/tokens are generated with `secrets` (cryptographically strong).
Session tokens are stored hashed (SHA-256) so a database leak does not
leak usable sessions. Passwords use argon2id with per-hash random salt.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except Exception:
        # Wrong password, malformed hash or stale parameters: deny access.
        return False


def generate_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_payload_hash(payload: dict | list | str) -> str:
    """Deterministic SHA-256 over a canonical JSON payload.

    Used to bind approvals and tool executions to the exact action payload
    (SRS §7, .aknja/workflows): approving a different payload must fail.
    """
    import json

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
