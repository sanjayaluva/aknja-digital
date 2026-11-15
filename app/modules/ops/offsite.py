"""Offsite backup copies to S3-compatible object storage (docs/22 §5A).

Cloudflare R2 (the verified OBJECT_STORAGE candidate) speaks the S3 API, so
the uploader implements the minimum needed for backup artifacts: SigV4-signed
PUT (upload) and GET (drill download) with httpx — no boto3, keeping the
dependency surface minimal and auditable (T-011 zero-unresolved rule).

Both the dump artifact and its manifest are pushed; the offsite drill
downloads the pair into a scratch directory and runs the ordinary restore
drill against them, proving the offsite copy is genuinely restorable.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import ConflictError
from app.core.security import utcnow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.modules.ops.models import BackupRecord

R2_REGION = "auto"  # Cloudflare R2 accepts "auto" for SigV4


# ------------------------------------------------------------- SigV4 signing


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sign_v4(
    *,
    method: str,
    url: str,
    payload: bytes,
    key_id: str,
    secret: str,
    amz_date: str | None = None,
    region: str = R2_REGION,
    service: str = "s3",
) -> dict[str, str]:
    """Return the headers that authorize one S3 request (SigV4, payload hashed)."""
    parsed = httpx.URL(url)
    host = parsed.host
    if parsed.port and (parsed.scheme == "http" and parsed.port != 80
                        or parsed.scheme == "https" and parsed.port != 443):
        host = f"{host}:{parsed.port}"
    datestamp = (amz_date or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    short_date = datestamp[:8]
    payload_hash = hashlib.sha256(payload).hexdigest()
    headers = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": datestamp,
    }
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
    canonical_request = (
        f"{method}\n{parsed.path}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )
    scope = f"{short_date}/{region}/{service}/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{datestamp}\n{scope}\n"
        f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )
    k_signing = _hmac(
        _hmac(_hmac(_hmac(("AWS4" + secret).encode(), short_date), region), service),
        "aws4_request",
    )
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    return {
        "x-amz-date": datestamp,
        "x-amz-content-sha256": payload_hash,
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }


# ------------------------------------------------------------ configuration


def offsite_target(settings: Settings | None = None) -> tuple[str, str, str, str] | None:
    """(endpoint, bucket, access_key_id, secret) when fully configured."""
    s = settings or get_settings()
    if not (s.object_storage_endpoint and s.object_storage_bucket
            and s.object_storage_access_key_id
            and s.object_storage_secret_access_key.get_secret_value()):
        return None
    return (
        s.object_storage_endpoint.rstrip("/"),
        s.object_storage_bucket,
        s.object_storage_access_key_id,
        s.object_storage_secret_access_key.get_secret_value(),
    )


# ------------------------------------------------------------- upload/get


def _object_url(endpoint: str, bucket: str, key: str) -> str:
    return f"{endpoint}/{bucket}/{key}"


def offsite_key_for(storage_key: str) -> str:
    """Remote object key for a backup artifact (manifest uses the same prefix)."""
    return f"backups/{storage_key}"


def manifest_storage_key(storage_key: str) -> str:
    return storage_key.replace(".dump", ".manifest.json")


def upload_object(
    key: str, data: bytes, *, settings: Settings | None = None,
    http_client: httpx.Client | None = None,
) -> None:
    """PUT one object to the configured S3 target; raise ConflictError on failure."""
    target = offsite_target(settings)
    if target is None:
        raise ConflictError(
            "offsite storage not configured: set OBJECT_STORAGE_ENDPOINT, "
            "OBJECT_STORAGE_BUCKET, OBJECT_STORAGE_ACCESS_KEY_ID and "
            "OBJECT_STORAGE_SECRET_ACCESS_KEY"
        )
    endpoint, bucket, key_id, secret = target
    url = _object_url(endpoint, bucket, key)
    headers = sign_v4(method="PUT", url=url, payload=data, key_id=key_id, secret=secret)
    client = http_client or httpx.Client(timeout=120)
    try:
        response = client.put(url, content=data, headers=headers)
        if response.status_code not in (200, 201):
            raise ConflictError(
                f"offsite upload of '{key}' failed: HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
    finally:
        if http_client is None:
            client.close()


def download_object(
    key: str, dest: Path, *, settings: Settings | None = None,
    http_client: httpx.Client | None = None,
) -> Path:
    """GET one object and write it to dest; checksum verification is caller-side."""
    target = offsite_target(settings)
    if target is None:
        raise ConflictError("offsite storage not configured")
    endpoint, bucket, key_id, secret = target
    url = _object_url(endpoint, bucket, key)
    headers = sign_v4(method="GET", url=url, payload=b"", key_id=key_id, secret=secret)
    client = http_client or httpx.Client(timeout=300)
    try:
        response = client.get(url, headers=headers)
        if response.status_code != 200:
            raise ConflictError(
                f"offsite download of '{key}' failed: HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        dest.write_bytes(response.content)
        return dest
    finally:
        if http_client is None:
            client.close()


# --------------------------------------------------------- push / drill ops


def push_backup_offsite(
    db: Session,
    record: BackupRecord,
    *,
    artifact: Path,
    settings: Settings | None = None,
    http_client: httpx.Client | None = None,
) -> str:
    """Upload a backup artifact + its manifest and mark the record offsite.

    The manifest is best-effort next to the dump: if it is missing locally
    the dump still uploads (the drill then verifies by checksum only).
    """
    from app.modules.governance.service import record_audit
    from app.modules.ops.backup import _manifest_path

    if record.offsite_key:
        return record.offsite_key  # idempotent: never double-push

    upload_object(
        offsite_key_for(record.storage_key), artifact.read_bytes(),
        settings=settings, http_client=http_client,
    )
    manifest = _manifest_path(artifact.parent, record.storage_key)
    if manifest.is_file():
        upload_object(
            offsite_key_for(manifest_storage_key(record.storage_key)),
            manifest.read_bytes(), settings=settings, http_client=http_client,
        )
    record.offsite_key = offsite_key_for(record.storage_key)
    record.offsite_at = utcnow()
    record_audit(
        db,
        tenant_id=record.tenant_id,
        actor_type="SYSTEM",
        actor_id="backup-service",
        action="backup.offsite_pushed",
        resource_type="backup_record",
        resource_id=str(record.id),
        payload={
            "storage_key": record.storage_key,
            "offsite_key": record.offsite_key,
            "size_bytes": record.size_bytes,
            "sha256": record.checksum[:16],
        },
    )
    db.commit()
    return record.offsite_key


def pull_backup_offsite(
    db: Session,
    record: BackupRecord,
    *,
    dest_dir: Path,
    settings: Settings | None = None,
    http_client: httpx.Client | None = None,
) -> tuple[Path, str]:
    """Download a record's offsite pair into dest_dir; verify the checksum.

    Returns (local artifact path, remote manifest key or "").
    """
    import hashlib as _hashlib

    from app.modules.ops.backup import _manifest_path

    if not record.offsite_key:
        raise ConflictError(f"backup '{record.storage_key}' has no offsite copy")
    dest_dir.mkdir(parents=True, exist_ok=True)
    artifact = dest_dir / record.storage_key
    download_object(
        record.offsite_key, artifact, settings=settings, http_client=http_client
    )
    digest = _hashlib.sha256(artifact.read_bytes()).hexdigest()
    if digest != record.checksum:
        artifact.unlink(missing_ok=True)
        raise ConflictError(
            f"offsite copy of '{record.storage_key}' failed checksum: "
            f"expected {record.checksum[:16]}… got {digest[:16]}…"
        )
    remote_manifest = offsite_key_for(manifest_storage_key(record.storage_key))
    try:
        download_object(
            remote_manifest,
            _manifest_path(dest_dir, record.storage_key),
            settings=settings, http_client=http_client,
        )
    except ConflictError:
        remote_manifest = ""  # manifest absent offsite — checksum drill only
    return artifact, remote_manifest
