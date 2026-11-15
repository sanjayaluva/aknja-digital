"""Backup/restore drills, pruning safety and maintenance write-freeze.

v5.3.2 §5A: "Database backup and tested restore" + "Write freeze /
maintenance mode during a controlled promotion". docs/22: a backup is not
proven until restored; never remove the last known-good backup; record
restore duration. All against real PostgreSQL (pg_dump/pg_restore from the
bundled cluster tooling).
"""

from __future__ import annotations

import json

import pytest

from app.modules.ops.backup import (
    create_backup,
    latest_backup_status,
    prune_backups,
    run_restore_drill,
    verify_backup,
)
from app.modules.ops.maintenance import (
    is_maintenance_enabled,
    maintenance_reason,
    set_maintenance_mode,
)
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

# ------------------------------------------------------------------ backup


def _latest_record(db):
    from sqlalchemy import select

    from app.modules.ops.models import BackupRecord

    return db.scalars(
        select(BackupRecord).order_by(BackupRecord.created_at_backup.desc().nullslast())
    ).first()


def test_create_verify_roundtrip(db, seed, tmp_path) -> None:
    from app.core.enums import UserRole
    from app.modules.crm import service as crm
    from app.modules.identity.service import Principal

    principal = Principal(
        user_id=seed.admin.id, email=seed.admin.email, tenant_id=seed.tenant.id,
        role=UserRole.SUPER_ADMIN, client_id=None, session_id=seed.admin.id,
        csrf_token="backup-test",
    )
    crm.create_lead(db, principal=principal, title="Backup roundtrip lead",
                    feasibility_score=50)
    db.commit()

    result = create_backup(db, backup_dir=tmp_path)
    assert result.artifact.is_file()
    assert result.artifact.stat().st_size == result.size_bytes > 0
    assert len(result.sha256) == 64
    assert result.table_counts["leads"] == 1
    assert result.duration_ms >= 0

    manifest = json.loads((tmp_path / f"{result.record.storage_key}.manifest.json").read_text())
    assert manifest["sha256"] == result.sha256
    assert manifest["table_counts"]["leads"] == 1

    # record + audit + founder notification are all in place
    assert result.record.checksum == result.sha256
    assert result.record.size_bytes == result.size_bytes
    from sqlalchemy import text

    audit = db.execute(text(
        "SELECT COUNT(*) FROM audit_events WHERE action = 'backup.created'"
    )).scalar()
    assert audit == 1
    outbox = db.execute(text(
        "SELECT COUNT(*) FROM notification_outbox WHERE template_key = 'backup.completed'"
    )).scalar()
    assert outbox == 1

    # verification passes, freshness SLO included
    verified = verify_backup(tmp_path, result.record.storage_key, max_age_hours=1.0)
    assert verified.ok, verified.reason
    assert latest_backup_status(db, tmp_path).ok


def test_restore_drill_roundtrip(db, seed, tmp_path) -> None:
    """docs/22: restore to an isolated DB, verify counts + audit chain."""
    created = create_backup(db, backup_dir=tmp_path)

    drill = run_restore_drill(db, storage_key=created.record.storage_key, backup_dir=tmp_path)
    assert drill.ok, drill.reason
    assert drill.counts_match and drill.alembic_match and drill.chain_valid
    assert drill.duration_ms >= 0
    # isolated target is dropped again
    from sqlalchemy import text

    leftover = db.execute(text(
        "SELECT COUNT(*) FROM pg_database WHERE datname = :n"
    ), {"n": drill.target_db}).scalar()
    assert leftover == 0

    record = _latest_record(db)
    assert record.restore_drilled_at is not None
    assert "drilled_ms=" in record.notes

    audit = db.execute(text(
        "SELECT COUNT(*) FROM audit_events WHERE action = 'backup.restore_drill'"
    )).scalar()
    assert audit == 1
    outbox = db.execute(text(
        "SELECT COUNT(*) FROM notification_outbox WHERE template_key = 'backup.drill_completed'"
    )).scalar()
    assert outbox == 1


def test_drill_refuses_unverified_backup(db, seed, tmp_path) -> None:
    from app.core.errors import ValidationAppError

    created = create_backup(db, backup_dir=tmp_path)
    with open(created.artifact, "ab") as fh:
        fh.write(b"tampered")

    result = verify_backup(tmp_path, created.record.storage_key)
    assert not result.ok  # size/sha mismatch caught
    with pytest.raises(ValidationAppError, match="Refusing to drill"):
        run_restore_drill(db, storage_key=created.record.storage_key, backup_dir=tmp_path)


def test_prune_keeps_last_verified(db, seed, tmp_path) -> None:
    """docs/22: pruning never removes the last known-good backup."""
    from pathlib import Path

    first = create_backup(db, backup_dir=tmp_path)
    second = create_backup(db, backup_dir=tmp_path)
    third = create_backup(db, backup_dir=tmp_path)

    # corrupt the newest artifact: it must be pruned, the good older ones kept
    third.artifact.write_bytes(b"broken")
    result = prune_backups(db, keep_last=2, backup_dir=tmp_path)
    assert result.refused_reason == ""
    assert second.record.storage_key in result.kept
    assert first.record.storage_key in result.kept
    assert third.record.storage_key in result.removed
    assert not third.artifact.exists()

    # now corrupt BOTH remaining: pruning must refuse (no verified backup left)
    second.artifact.write_bytes(b"broken")
    first.artifact.write_bytes(b"broken")
    refused = prune_backups(db, keep_last=1, backup_dir=tmp_path)
    assert refused.refused_reason.startswith("refused")
    assert Path(first.artifact).exists()  # nothing was deleted


def test_prune_keep_last_happy_path(db, seed, tmp_path) -> None:
    one = create_backup(db, backup_dir=tmp_path)
    two = create_backup(db, backup_dir=tmp_path)
    three = create_backup(db, backup_dir=tmp_path)

    result = prune_backups(db, keep_last=1, backup_dir=tmp_path)
    assert result.kept == [three.record.storage_key]
    assert set(result.removed) == {one.record.storage_key, two.record.storage_key}
    assert not one.artifact.exists() and not two.artifact.exists()
    assert three.artifact.is_file()
    # manifests are pruned alongside their artifacts
    assert not (tmp_path / f"{one.record.storage_key}.manifest.json").exists()


# ------------------------------------------------------------- maintenance


def test_maintenance_toggle_semantics(db, seed) -> None:
    from sqlalchemy import text

    changed, previous = set_maintenance_mode(db, enabled=True, reason="promotion drill")
    assert changed and previous is False
    assert is_maintenance_enabled() is True
    assert maintenance_reason() == "promotion drill"

    # idempotent: re-asserting ON neither audits nor notifies again
    changed, _ = set_maintenance_mode(db, enabled=True, reason="again")
    assert changed is False
    enabled_audits = db.execute(text(
        "SELECT COUNT(*) FROM audit_events WHERE action = 'maintenance.enabled'"
    )).scalar()
    activated_notes = db.execute(text(
        "SELECT COUNT(*) FROM notification_outbox WHERE template_key = 'maintenance.activated'"
    )).scalar()
    assert enabled_audits == 1
    assert activated_notes == 1

    changed, previous = set_maintenance_mode(db, enabled=False)
    assert changed and previous is True
    assert is_maintenance_enabled() is False
    deactivated = db.execute(text(
        "SELECT COUNT(*) FROM notification_outbox WHERE template_key = 'maintenance.deactivated'"
    )).scalar()
    assert deactivated == 1


def test_maintenance_freeze_blocks_writes_not_reads(db, seed, client) -> None:
    set_maintenance_mode(db, enabled=True, reason="controlled promotion")

    # reads stay up (console + health + api list)
    assert client.get("/login").status_code == 200
    assert client.get("/healthz").status_code == 200

    # any mutating request (even unauthenticated) is 503 + Retry-After
    resp = client.post("/api/v1/leads", json={"title": "frozen"})
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "30"
    assert resp.json()["error"]["code"] == "MAINTENANCE_MODE"
    assert "promotion" in resp.json()["error"]["message"]

    # auth stays usable during the freeze
    resp = client.post(
        "/api/v1/auth/login",
        data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200

    set_maintenance_mode(db, enabled=False)
    # writes flow again (401 here proves the request reached routing, not the freeze)
    resp = client.post("/api/v1/leads", json={"title": "unfrozen"})
    assert resp.status_code != 503
