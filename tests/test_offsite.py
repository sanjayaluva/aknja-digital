"""Offsite backup copies to S3-compatible storage (docs/22 §5A, T-018).

Rules under test:
- SigV4 signing is deterministic and structurally correct (golden pin guards
  regressions; the live R2 roundtrip is the authoritative acceptance proof);
- pushing marks the BackupRecord (offsite_key/offsite_at) with an audit event
  and is idempotent — a second push uploads nothing;
- pulling verifies the sha256 against the record and refuses tampered copies;
- any non-2xx from the object store raises ConflictError (fail closed).
"""

from __future__ import annotations

import hashlib

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import ConflictError
from app.modules.ops.backup import create_backup
from app.modules.ops.offsite import (
    list_objects,
    offsite_key_for,
    pull_backup_offsite,
    push_backup_offsite,
    sign_v4,
    upload_object,
)

GOLDEN_AUTH = (
    "AWS4-HMAC-SHA256 "
    "Credential=AKIAIOSFODNN7EXAMPLE/20261115/auto/s3/aws4_request, "
    "SignedHeaders=host;x-amz-content-sha256;x-amz-date, "
    "Signature=d4892b378a7eb58f94cc18a09fff37895ba55932fa4763eaa0149c17d3228e72"
)

GOLDEN_AUTH_QUERY = (
    "AWS4-HMAC-SHA256 "
    "Credential=AKIAIOSFODNN7EXAMPLE/20261115/auto/s3/aws4_request, "
    "SignedHeaders=host;x-amz-content-sha256;x-amz-date, "
    "Signature=1192ba963fe4abfc025fe48c94a2694007e48bcae3ec53731f2acda596e5ea7b"
)


def _settings(tmp_path, **overrides) -> Settings:
    base = {
        "storage_backend": "s3",
        "object_storage_endpoint": "https://s3.example.internal",
        "object_storage_bucket": "aknja-test",
        "object_storage_access_key_id": "test-key-id",
        "object_storage_secret_access_key": "test-secret",
        "backup_dir": str(tmp_path / "backups"),
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_sigv4_query_string_is_signed_and_order_insensitive() -> None:
    """ListObjectsV2-style requests: the query string is part of the canonical
    request (the pre-T-024 empty-string bug produced 403 SignatureDoesNotMatch)."""
    kw = {
        "method": "GET", "payload": b"", "key_id": "AKIAIOSFODNN7EXAMPLE",
        "secret": "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        "amz_date": "20261115T120000Z", "region": "auto",
    }
    canonical_order = sign_v4(url="https://s3.example.internal/bucket?list-type=2&prefix=backups%2F", **kw)
    assert canonical_order["Authorization"] == GOLDEN_AUTH_QUERY
    # a different parameter order yields the SAME signature (sorted canonical)
    shuffled = sign_v4(url="https://s3.example.internal/bucket?prefix=backups%2F&list-type=2", **kw)
    assert shuffled["Authorization"] == GOLDEN_AUTH_QUERY
    # and the query clearly changes the signature vs the bare bucket URL
    bare = sign_v4(url="https://s3.example.internal/bucket", **kw)
    assert bare["Authorization"] != GOLDEN_AUTH_QUERY


def test_list_objects_parses_keys(tmp_path) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(200, text=(
            '<?xml version="1.0"?>'
            "<ListBucketResult>"
            "<Name>aknja-test</Name>"
            "<Contents><Key>backups/a.dump</Key></Contents>"
            "<Contents><Key>backups/a.dump.manifest.json</Key></Contents>"
            "</ListBucketResult>"
        ))

    keys = list_objects(
        "backups/", settings=_settings(tmp_path),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert keys == ["backups/a.dump", "backups/a.dump.manifest.json"]
    assert "list-type=2" in seen["url"] and "prefix=backups%2F" in seen["url"]
    assert seen["auth"].startswith("AWS4-HMAC-SHA256")


def test_sigv4_golden_and_structure() -> None:
    headers = sign_v4(
        method="PUT", url="https://s3.example.internal/bucket/backups/x.dump",
        payload=b"deterministic payload\n",
        key_id="AKIAIOSFODNN7EXAMPLE",
        secret="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        amz_date="20261115T120000Z", region="auto",
    )
    assert headers["Authorization"] == GOLDEN_AUTH  # regression pin
    assert headers["x-amz-date"] == "20261115T120000Z"
    assert headers["x-amz-content-sha256"] == hashlib.sha256(
        b"deterministic payload\n"
    ).hexdigest()


def test_upload_fails_closed_on_http_error(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="SignatureDoesNotMatch")
    with pytest.raises(ConflictError, match="HTTP 403"):
        upload_object(
            "backups/x.dump", b"data", settings=_settings(tmp_path),
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )


def test_push_marks_record_idempotent_and_audited(db, seed, tmp_path) -> None:
    from sqlalchemy import select

    from app.modules.governance.models import AuditEvent
    from app.modules.ops.models import BackupRecord

    result = create_backup(db, backup_dir=tmp_path / "backups")
    settings = _settings(tmp_path)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    key = push_backup_offsite(
        db, result.record, artifact=result.artifact,
        settings=settings, http_client=client,
    )
    assert key == offsite_key_for(result.record.storage_key)
    record = db.get(BackupRecord, result.record.id)
    assert record.offsite_key == key
    assert record.offsite_at is not None
    assert [r.method for r in seen] == ["PUT", "PUT"]  # dump + manifest

    audit = db.scalars(
        select(AuditEvent).where(AuditEvent.action == "backup.offsite_pushed")
    ).all()
    assert len(audit) == 1
    assert audit[0].resource_id == str(record.id)

    seen.clear()
    again = push_backup_offsite(
        db, record, artifact=result.artifact,
        settings=settings, http_client=client,
    )
    assert again == key and seen == []  # idempotent: no re-upload


def test_pull_verifies_checksum_and_rejects_tamper(db, seed, tmp_path) -> None:
    result = create_backup(db, backup_dir=tmp_path / "backups")
    settings = _settings(tmp_path)
    good = result.artifact.read_bytes()
    state = {"tamper": False}

    def handler(request: httpx.Request) -> httpx.Response:
        body = good if not state["tamper"] else b"corrupted bytes"
        return httpx.Response(200, content=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    push_backup_offsite(
        db, result.record, artifact=result.artifact,
        settings=settings, http_client=client,
    )
    dest = tmp_path / "offsite-download"
    artifact, remote_manifest = pull_backup_offsite(
        db, result.record, dest_dir=dest, settings=settings, http_client=client,
    )
    assert artifact.is_file()
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == result.record.checksum
    assert remote_manifest  # manifest served in the happy path

    state["tamper"] = False
    record2 = create_backup(db, backup_dir=tmp_path / "backups").record
    push_backup_offsite(
        db, record2, artifact=tmp_path / "backups" / record2.storage_key,
        settings=settings, http_client=client,
    )
    state["tamper"] = True
    with pytest.raises(ConflictError, match="failed checksum"):
        pull_backup_offsite(
            db, record2, dest_dir=dest, settings=settings, http_client=client,
        )
    assert not (dest / record2.storage_key).exists()  # refused copy not kept
