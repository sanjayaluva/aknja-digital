"""Monitor: detection -> incident lifecycle -> safe recovery (docs/20, Phase 8).

Phase 8 exit criteria: injected failure detected; safe recovery verified;
unsafe action blocked. All checks run against real PostgreSQL; the LLM is
either absent (fail-closed) or monkeypatched — no network in tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.errors import ConflictError
from app.modules.ops.models import (
    BackupRecord,
    Incident,
    Job,
    NotificationOutbox,
    SystemSetting,
)
from app.modules.ops.monitor import (
    RECOVERY_ACTIONS,
    diagnose_incident,
    redact,
    run_monitor,
    run_recovery_action,
)

# ------------------------------------------------------------------ helpers


def _now() -> datetime:
    return datetime.now(UTC)


def _fresh_backup(db, tenant_id) -> None:
    db.add(
        BackupRecord(
            tenant_id=tenant_id,
            scope="DATABASE",
            storage_key="monitor-test.backup",
            checksum="x" * 64,
            size_bytes=10,
            encrypted=False,
            created_at_backup=_now(),
        )
    )
    db.commit()


def _stuck_job(db, tenant_id, minutes: int = 60) -> Job:
    job = Job(
        tenant_id=tenant_id,
        kind="test.requeue",
        payload={},
        run_at=_now() - timedelta(minutes=minutes),
    )
    db.add(job)
    db.commit()
    return job


def _stuck_notification(db, tenant_id, minutes: int = 120) -> NotificationOutbox:
    row = NotificationOutbox(
        tenant_id=tenant_id,
        template_key="incident.opened",
        body="stuck",
        idempotency_key=f"monitor-test-{uuid.uuid4()}",
        created_at=_now() - timedelta(minutes=minutes),
    )
    db.add(row)
    db.commit()
    return row


def _incidents(db) -> list[Incident]:
    return list(db.scalars(select(Incident)).all())


# ------------------------------------------------------------------- checks


def test_healthy_platform_creates_no_incidents(db, seed):
    _fresh_backup(db, seed.tenant.id)
    summary = run_monitor(db)
    assert all(r["ok"] for r in summary.values())
    assert _incidents(db) == []


def test_missing_backup_opens_critical_incident_and_notifies(db, seed):
    summary = run_monitor(db)  # no backup record at all
    assert summary["backup_freshness"]["ok"] is False
    assert summary["backup_freshness"]["severity"] == "CRITICAL"
    assert summary["backup_freshness"]["recovery"] is None  # operator action, no auto-fix

    (incident,) = _incidents(db)
    assert incident.severity == "CRITICAL"
    assert incident.description.startswith("[backup_freshness]")
    assert incident.timeline[0]["event"] == "DETECTED"

    notified = db.scalars(
        select(NotificationOutbox).where(
            NotificationOutbox.idempotency_key == f"incident:{incident.id}:opened"
        )
    ).all()
    assert len(notified) == 1 and notified[0].template_key == "incident.opened"


def test_second_run_dedupes_onto_the_same_incident(db, seed):
    first = run_monitor(db)["backup_freshness"]["incident_id"]
    second = run_monitor(db)["backup_freshness"]["incident_id"]
    assert first == second
    assert len(_incidents(db)) == 1
    (incident,) = _incidents(db)
    events = [e["event"] for e in incident.timeline]
    assert events.count("DETECTED") == 1
    assert "RE_DETECTED" in events


def test_recovery_resolves_incident_and_notifies(db, seed):
    run_monitor(db)  # opens the backup incident
    (incident,) = _incidents(db)
    _fresh_backup(db, seed.tenant.id)
    summary = run_monitor(db)
    assert summary["backup_freshness"]["ok"] is True
    assert incident.status == "RESOLVED"
    assert incident.resolved_at is not None
    assert incident.timeline[-1]["event"] == "RESOLVED"
    resolved = db.scalars(
        select(NotificationOutbox).where(
            NotificationOutbox.idempotency_key == f"incident:{incident.id}:resolved"
        )
    ).all()
    assert len(resolved) == 1 and resolved[0].template_key == "incident.resolved"


def test_stuck_jobs_detected_and_requeued(db, seed):
    job = _stuck_job(db, seed.tenant.id)
    _fresh_backup(db, seed.tenant.id)  # keep unrelated checks green

    summary = run_monitor(db)
    assert summary["job_queue"]["ok"] is False
    assert summary["job_queue"]["severity"] == "MEDIUM"
    assert "requeue_stuck_jobs (1 item(s))" == summary["job_queue"]["recovery"]

    db.refresh(job)
    assert job.run_at >= _now() - timedelta(seconds=5)  # due again now
    (incident,) = [i for i in _incidents(db) if i.description.startswith("[job_queue]")]
    assert incident.recovery_actions[0]["action"] == "requeue_stuck_jobs"
    assert any(e["event"] == "RECOVERY" for e in incident.timeline)


def test_stuck_notifications_requeued_idempotently(db, seed):
    row = _stuck_notification(db, seed.tenant.id)
    _fresh_backup(db, seed.tenant.id)

    summary = run_monitor(db)
    assert summary["notification_queue"]["ok"] is False
    assert summary["notification_queue"]["severity"] == "HIGH"
    db.refresh(row)
    assert row.next_attempt_at is not None
    assert row.next_attempt_at >= _now() - timedelta(seconds=5)
    # idempotent by construction: the outbox dedupes on idempotency_key,
    # and the requeue only touches next_attempt_at
    assert row.status == "PENDING"
    assert row.idempotency_key.startswith("monitor-test-")


# ----------------------------------------------------------- safety gates


def test_unknown_recovery_actions_are_refused(db):
    """docs/20: no code path may exist for the autonomous-forbidden class."""
    for unsafe in ("drop_database", "delete_data", "rotate_dns", "rotate_credentials",
                   "alter_auth_policy", "deploy_production", "provision_paid_capacity",
                   "restart_stateless_service"):
        with pytest.raises(ConflictError):
            run_recovery_action(db, unsafe)
    assert set(RECOVERY_ACTIONS) == {"requeue_stuck_jobs", "requeue_stuck_notifications"}


def test_circuit_breaker_caps_recovery_per_hour(db, seed):
    setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "recovery_actions_max_per_hour")
    )
    setting.value_json = 1  # one autonomous action per hour
    db.commit()
    _fresh_backup(db, seed.tenant.id)
    _stuck_job(db, seed.tenant.id)
    _stuck_notification(db, seed.tenant.id)

    run_monitor(db)  # notification_queue check runs before job_queue

    executed = [i for i in _incidents(db) if i.recovery_actions]
    skipped = [
        i for i in _incidents(db)
        if any(e["event"] == "RECOVERY_SKIPPED" for e in i.timeline)
    ]
    assert len(executed) == 1 and len(skipped) == 1
    skipped_entry = next(e for e in skipped[0].timeline if e["event"] == "RECOVERY_SKIPPED")
    assert "circuit breaker" in skipped_entry["reason"]


# ---------------------------------------------------------- AI diagnosis


def test_diagnose_fails_closed_without_verified_provider(db, seed):
    run_monitor(db)  # open the backup incident
    (incident,) = _incidents(db)

    result = diagnose_incident(db, incident.id)
    assert result["status"] == "PENDING_MANUAL"
    db.refresh(incident)
    entry = incident.timeline[-1]
    assert entry["event"] == "AI_DIAGNOSIS" and entry["status"] == "PENDING_MANUAL"


def test_diagnose_records_redacted_summary(db, seed, monkeypatch):
    from app.modules.ai.inference import LLMResult

    def fake_complete(*_args, **_kwargs):
        return LLMResult(
            status="SUCCEEDED",
            text="Likely cause: backup job never ran. Contact founder@example.com "
                 "or use token=sk-live-abc123. Proposed: run `aknja backup create` "
                 "and review the scheduler.",
        )

    monkeypatch.setattr("app.modules.ai.inference.llm_complete", fake_complete)

    run_monitor(db)
    (incident,) = _incidents(db)
    result = diagnose_incident(db, incident.id)

    assert result["status"] == "SUCCEEDED"
    assert "founder@example.com" not in result["diagnosis"]
    assert "[redacted-email]" in result["diagnosis"]
    assert "[redacted-credential]" in result["diagnosis"]
    db.refresh(incident)
    assert incident.status == "INVESTIGATING"
    assert incident.timeline[-1]["event"] == "AI_DIAGNOSIS"


def test_redact_strips_each_pattern():
    text = redact(
        "mail a@b.io password=hunter2 hash 0123456789abcdef0123456789abcdef "
        "url https://user:pw@example.com/x"
    )
    assert "a@b.io" not in text and "[redacted-email]" in text
    assert "hunter2" not in text and "[redacted-credential]" in text
    assert "0123456789abcdef0123456789abcdef" not in text
    assert "[redacted-url-cred]" in text
