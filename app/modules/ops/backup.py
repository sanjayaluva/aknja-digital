"""Database backup, verified restore drills and safe pruning.

v5.3.2 §5A (relational database pool): "Database backup and tested restore"
and "Write freeze / maintenance mode during a controlled promotion". docs/22:
a backup is not proven until restored; never overwrite the only known-good
backup during a failed restore; record restore duration and the achieved
data-loss window.

Artifacts are pg_dump custom-format archives (``-Fc --no-owner
--no-privileges``) with a sidecar JSON manifest (sha256, size, row counts,
alembic head) used by ``verify_backup`` and the restore drill. At-rest
encryption is the storage backend's responsibility (docs/22: encryption at
rest and in transit), so records are flagged ``encrypted=False`` and the
off-host copy is an ops-runbook step, not code.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Base
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.security import utcnow
from app.modules.governance.service import record_audit, verify_audit_chain
from app.modules.ops.models import BackupRecord
from app.modules.ops.notifications import notify_admin

# ---------------------------------------------------------------- helpers


def find_pg_binary(name: str) -> str:
    """Locate a PostgreSQL client binary: explicit setting, the pgserver
    bundle (sandbox/CI), then PATH."""
    settings = get_settings()
    candidates = []
    if settings.pg_bin_dir:
        candidates.append(Path(settings.pg_bin_dir) / name)
    try:
        import pgserver as _pgserver

        candidates.append(Path(_pgserver.__file__).parent / "pginstall" / "bin" / name)
    except ImportError:  # pragma: no cover - production hosts
        pass
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate and candidate.is_file():
            return str(candidate)
    raise ConflictError(
        f"PostgreSQL binary '{name}' not found — set pg_bin_dir or install postgresql-client"
    )


def _to_libpq_uri(database_url: str) -> str:
    """``postgresql+psycopg://...`` -> libpq URI understood by pg_dump/restore."""
    if "+psycopg://" in database_url:
        return database_url.replace("+psycopg://", "://", 1)
    return database_url


def _admin_uri(database_url: str) -> str:
    """URI of the same cluster's maintenance database (for CREATE/DROP DATABASE)."""
    uri = _to_libpq_uri(database_url)
    base, _, query = uri.partition("?")
    if "/" in base:
        head, _, _db = base.rpartition("/")
        base = f"{head}/postgres"
    return f"{base}?{query}" if query else base


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_counts(db: Session) -> dict[str, int]:
    import app.models  # noqa: F401 — full registry: partial imports break FK resolution

    counts: dict[str, int] = {}
    for table in sorted(Base.metadata.sorted_tables, key=lambda t: t.name):
        counts[table.name] = int(db.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar() or 0)
    return counts


def _alembic_head(db: Session) -> str | None:
    """Current alembic revision (None when the schema was created without
    alembic, e.g. dev bootstrap via create_all). Checked with to_regclass so
    a missing table never poisons the caller's transaction."""
    if db.execute(text("SELECT to_regclass('public.alembic_version')")).scalar() is None:
        return None
    return db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def _manifest_path(backup_dir: Path, storage_key: str) -> Path:
    return backup_dir / f"{storage_key}.manifest.json"


def _load_manifest(backup_dir: Path, storage_key: str) -> dict:
    path = _manifest_path(backup_dir, storage_key)
    if not path.is_file():
        raise NotFoundError(f"Manifest missing for backup '{storage_key}'")
    return json.loads(path.read_text())


# ---------------------------------------------------------------- create


@dataclass
class CreateResult:
    record: BackupRecord
    artifact: Path
    sha256: str
    size_bytes: int
    duration_ms: int
    table_counts: dict[str, int] = field(default_factory=dict)


def create_backup(
    db: Session, *, tenant_id: uuid.UUID | None = None, backup_dir: str | Path | None = None
) -> CreateResult:
    """Dump the primary database to a new timestamped artifact + manifest.

    Never touches existing artifacts (docs/22: no overwrite during failures).
    """
    settings = get_settings()
    directory = Path(backup_dir) if backup_dir else Path(settings.backup_dir)
    directory.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    storage_key = f"aknja-{stamp}-{uuid.uuid4().hex[:8]}.dump"
    artifact = directory / storage_key

    dump = find_pg_binary("pg_dump")
    result = subprocess.run(
        [
            dump,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(artifact),
            _to_libpq_uri(settings.database_url),
        ],
        check=False,  # rc + stderr handled explicitly below
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0 or not artifact.is_file():
        if artifact.exists():
            artifact.unlink()  # partial dump must never linger as a "backup"
        raise ConflictError(f"pg_dump failed ({result.returncode}): {result.stderr[-800:]}")

    sha256 = _sha256_file(artifact)
    size = artifact.stat().st_size
    counts = _table_counts(db)
    head = _alembic_head(db)
    manifest = {
        "artifact": storage_key,
        "sha256": sha256,
        "size_bytes": size,
        "created_at": datetime.now(UTC).isoformat(),
        "alembic_head": head,
        "table_counts": counts,
        "pg_dump": dump,
    }
    _manifest_path(directory, storage_key).write_text(json.dumps(manifest, indent=2))

    duration_ms = int((time.monotonic() - started) * 1000)
    record = BackupRecord(
        tenant_id=tenant_id or _internal_tenant_id(db),
        scope="DATABASE",
        storage_key=storage_key,
        checksum=sha256,
        size_bytes=size,
        encrypted=False,  # at-rest encryption is the storage backend's duty
        created_at_backup=utcnow(),
        notes=f"rows={sum(counts.values())} duration_ms={duration_ms}",
    )
    db.add(record)
    db.flush()
    record_audit(
        db,
        tenant_id=record.tenant_id,
        actor_type="SYSTEM",
        actor_id="backup-service",
        action="backup.created",
        resource_type="backup_record",
        resource_id=str(record.id),
        payload={"storage_key": storage_key, "size_bytes": size, "sha256": sha256[:16]},
    )
    notify_admin(
        db,
        template_key="backup.completed",
        payload={"storage_key": storage_key, "size_mb": size / 1_048_576},
        idempotency_key=f"backup.completed:{storage_key}",
        tenant_id=record.tenant_id,
    )
    db.commit()
    return CreateResult(record, artifact, sha256, size, duration_ms, counts)


def _internal_tenant_id(db: Session) -> uuid.UUID:
    row = db.execute(text("SELECT id FROM tenants ORDER BY created_at LIMIT 1")).scalar_one_or_none()
    if row is None:
        raise ConflictError("No tenant exists — run init-db first")
    return row


# ---------------------------------------------------------------- verify


@dataclass
class VerifyResult:
    storage_key: str
    ok: bool
    reason: str = ""
    age_hours: float | None = None


def verify_backup(
    backup_dir: str | Path | None, storage_key: str, *, max_age_hours: float | None = None
) -> VerifyResult:
    """Checksum/size verification against the manifest; optional freshness SLO."""
    directory = Path(backup_dir) if backup_dir else Path(get_settings().backup_dir)
    artifact = directory / storage_key
    if not artifact.is_file():
        return VerifyResult(storage_key, False, "artifact file missing")
    try:
        manifest = _load_manifest(directory, storage_key)
    except NotFoundError as exc:
        return VerifyResult(storage_key, False, str(exc))
    if artifact.stat().st_size != manifest["size_bytes"]:
        return VerifyResult(storage_key, False, "size mismatch vs manifest")
    if _sha256_file(artifact) != manifest["sha256"]:
        return VerifyResult(storage_key, False, "sha256 mismatch vs manifest")

    age_hours: float | None = None
    if max_age_hours is not None:
        created = datetime.fromisoformat(manifest["created_at"])
        age_hours = (datetime.now(UTC) - created).total_seconds() / 3600
        if age_hours > max_age_hours:
            return VerifyResult(
                storage_key, False, f"stale: {age_hours:.1f}h > {max_age_hours}h SLO", age_hours
            )
    return VerifyResult(storage_key, True, "checksum+size match manifest", age_hours)


def latest_backup_status(db: Session, backup_dir: str | Path | None = None) -> VerifyResult | None:
    """Newest backup record + its verification (docs/22 freshness monitoring)."""
    records = _latest_records(db, 1)
    if not records:
        return None
    return verify_backup(backup_dir, records[0].storage_key)


def _latest_records(db: Session, limit: int) -> list[BackupRecord]:
    from sqlalchemy import select

    return list(
        db.scalars(
            select(BackupRecord).order_by(BackupRecord.created_at_backup.desc().nullslast()).limit(limit)
        )
    )


# ---------------------------------------------------------------- restore drill


@dataclass
class DrillResult:
    storage_key: str
    ok: bool
    duration_ms: int
    target_db: str
    counts_match: bool = True
    alembic_match: bool = True
    chain_valid: bool = True
    reason: str = ""


def run_restore_drill(
    db: Session,
    *,
    storage_key: str | None = None,
    backup_dir: str | Path | None = None,
    drop_target: bool = True,
) -> DrillResult:
    """Restore a backup into an ISOLATED scratch database and verify it.

    Never reads/writes the primary database's data (docs/22: restore drill to
    isolated environment; a failed restore never touches the only known-good
    backup — the artifact is opened read-only).
    """
    import psycopg

    settings = get_settings()
    directory = Path(backup_dir) if backup_dir else Path(settings.backup_dir)

    record = None
    if storage_key is None:
        latest = _latest_records(db, 1)
        if not latest:
            raise NotFoundError("No backup records exist — create one first")
        record, storage_key = latest[0], latest[0].storage_key
    else:
        from sqlalchemy import select

        found = db.scalars(
            select(BackupRecord).where(BackupRecord.storage_key == storage_key)
        ).one_or_none()
        if found is None:
            raise NotFoundError(f"No backup record for '{storage_key}'")
        record = found

    verify = verify_backup(directory, storage_key)
    if not verify.ok:
        raise ValidationAppError(f"Refusing to drill an unverified backup: {verify.reason}")

    manifest = _load_manifest(directory, storage_key)
    artifact = directory / storage_key
    target_db = f"aknja_drill_{uuid.uuid4().hex[:10]}"
    target_uri = _to_libpq_uri(settings.database_url)
    # swap the database name in the URI for the scratch target
    base, _, query = target_uri.partition("?")
    head, _, _ = base.rpartition("/")
    target_uri = f"{head}/{target_db}" + (f"?{query}" if query else "")

    started = time.monotonic()
    try:
        with psycopg.connect(_admin_uri(settings.database_url), autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{target_db}"')
        restore = find_pg_binary("pg_restore")
        result = subprocess.run(
            [restore, "--no-owner", "--no-privileges", "--dbname", target_uri, str(artifact)],
            check=False,  # rc + stderr handled explicitly below
            capture_output=True,
            text=True,
            timeout=600,
        )
        ok = result.returncode == 0
        reason = f"pg_restore exit {result.returncode}: {result.stderr[-800:]}" if not ok else ""

        counts_match = alembic_match = chain_valid = True
        if ok:
            counts_match, alembic_match, chain_valid, reason = _verify_restored(
                target_uri, manifest
            )
            ok = counts_match and alembic_match and chain_valid
    finally:
        if drop_target:
            try:
                with psycopg.connect(_admin_uri(settings.database_url), autocommit=True) as conn:
                    conn.execute(f'DROP DATABASE IF EXISTS "{target_db}" WITH (FORCE)')
            except Exception:  # pragma: no cover — best-effort cleanup
                import logging

                logging.getLogger("aknja.backup").warning(
                    "drill scratch db %s not dropped", target_db, exc_info=True
                )

    duration_ms = int((time.monotonic() - started) * 1000)
    if ok:
        record.restore_drilled_at = utcnow()
        record.notes = f"{record.notes} drilled_ms={duration_ms}"
        db.flush()
    record_audit(
        db,
        tenant_id=record.tenant_id,
        actor_type="SYSTEM",
        actor_id="backup-service",
        action="backup.restore_drill",
        resource_type="backup_record",
        resource_id=str(record.id),
        payload={"storage_key": storage_key, "ok": ok, "duration_ms": duration_ms,
                 "target_db": target_db, "reason": reason[:200]},
    )
    notify_admin(
        db,
        template_key="backup.drill_completed" if ok else "backup.drill_failed",
        payload={"storage_key": storage_key, "duration_s": duration_ms / 1000,
                 "reason": reason[:120]},
        idempotency_key=f"backup.drill:{storage_key}:{record.restore_drilled_at or utcnow():%Y%m%d%H%M%S}",
        tenant_id=record.tenant_id,
    )
    db.commit()
    return DrillResult(storage_key, ok, duration_ms, target_db,
                       counts_match, alembic_match, chain_valid, reason)


def _verify_restored(target_uri: str, manifest: dict) -> tuple[bool, bool, bool, str]:
    """Open the restored database and check counts, alembic head, audit chain."""
    from sqlalchemy import create_engine
    from sqlalchemy import text as sa_text
    from sqlalchemy.orm import Session

    engine = create_engine(target_uri)
    try:
        with Session(engine) as target:
            counts_match = True
            for table, expected in manifest["table_counts"].items():
                actual = target.execute(sa_text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
                if actual != expected:
                    counts_match = False
            alembic_match = True
            # to_regclass guard: a missing alembic_version must not poison
            # the transaction before the audit-chain check runs
            if target.execute(
                sa_text("SELECT to_regclass('public.alembic_version')")
            ).scalar() is None:
                alembic_match = manifest["alembic_head"] is None
            else:
                head = target.execute(
                    sa_text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
                alembic_match = head == manifest["alembic_head"]
            chain_valid = True
            reason = ""
            try:
                chain_valid = verify_audit_chain(target)
                if not chain_valid:
                    reason = "audit chain broken in restored database"
            except Exception as exc:  # noqa: BLE001 — report, never crash the drill
                chain_valid = False
                reason = f"audit chain check error: {exc}"
            return counts_match, alembic_match, chain_valid, reason
    finally:
        engine.dispose()


# ---------------------------------------------------------------- prune


@dataclass
class PruneResult:
    kept: list[str]
    removed: list[str]
    refused_reason: str = ""


def prune_backups(
    db: Session, *, keep_last: int = 5, backup_dir: str | Path | None = None
) -> PruneResult:
    """Delete old artifacts, never the last known-good backup (docs/22).

    A backup may only be pruned when (a) at least ``keep_last`` verified
    backups newer than it remain and (b) at least one verified backup would
    survive. Unverified (corrupt/missing) old artifacts are pruned too, but
    never as the last remaining artifact.
    """
    if keep_last < 1:
        raise ValidationAppError("keep_last must be >= 1")
    from sqlalchemy import select

    directory = Path(backup_dir) if backup_dir else Path(get_settings().backup_dir)
    records = list(
        db.scalars(select(BackupRecord).order_by(BackupRecord.created_at_backup.desc().nullslast()))
    )
    if not records:
        return PruneResult([], [], "no backups exist")

    verified: list[BackupRecord] = []
    for rec in records:
        if verify_backup(directory, rec.storage_key).ok:
            verified.append(rec)
    if not verified:
        return PruneResult([], [r.storage_key for r in records],
                           "refused: no verified backup would remain")

    keep = {r.storage_key for r in verified[:keep_last]}
    removed: list[str] = []
    for rec in records:
        if rec.storage_key in keep:
            continue
        artifact = directory / rec.storage_key
        if rec.storage_key not in {v.storage_key for v in verified}:
            # unverified (stale/corrupt) and not among the newest good ones:
            # safe to remove, it is not "known-good"
            if len(verified) >= 1:
                artifact.unlink(missing_ok=True)
                _manifest_path(directory, rec.storage_key).unlink(missing_ok=True)
                db.delete(rec)
                removed.append(rec.storage_key)
            continue
        artifact.unlink(missing_ok=True)
        _manifest_path(directory, rec.storage_key).unlink(missing_ok=True)
        db.delete(rec)
        removed.append(rec.storage_key)
    record_audit(
        db,
        tenant_id=verified[0].tenant_id,
        actor_type="SYSTEM",
        actor_id="backup-service",
        action="backup.pruned",
        resource_type="backup_record",
        resource_id=verified[0].storage_key,
        payload={"removed": removed, "kept": sorted(keep)},
    )
    db.commit()
    return PruneResult(sorted(keep), removed)
