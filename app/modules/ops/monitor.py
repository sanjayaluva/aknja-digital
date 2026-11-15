"""Platform health monitor: checks -> incident lifecycle -> safe recovery.

Implements the Phase 8 automation slice of docs/20 (production monitoring,
incidents and AI-assisted recovery) on top of the T-010 building blocks:

- **Detection** — backup freshness (docs/22 SLO), notification/job queue age,
  database blocking locks. Each check is a pure function returning a
  ``CheckResult``.
- **Lifecycle** — failing checks dedupe onto OPEN incidents (description
  convention ``[<check>] ...``); recovery auto-resolves them. Every
  transition appends to the JSONB timeline; the founder is notified on open
  and resolve through the durable outbox (idempotent keys per incident).
- **Safe recovery** — an EXHAUSTIVE allow-list of idempotent requeue actions.
  ``run_recovery_action`` refuses anything else with ``ConflictError``; the
  docs/20 "AI may not autonomously" class (data deletion, auth policy,
  DNS/credentials, schema, deploys, paid capacity) has no code path at all.
  A rolling-window circuit breaker caps actions per hour so remediation
  cannot loop (docs/20).
- **AI diagnosis** — ``diagnose_incident`` summarizes a redacted incident
  context through the governed inference layer (``summarization`` profile).
  Fail-closed: without a verified free provider it records
  PENDING_MANUAL in the timeline and returns; it never executes actions.

CLI: ``aknja monitor run`` / ``aknja monitor diagnose <incident-id>``.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.enums import IncidentSeverity, IncidentStatus
from app.core.errors import ConflictError
from app.modules.ops.models import BackupRecord, Incident, Job, NotificationOutbox
from app.modules.ops.notifications import notify_admin
from app.modules.ops.settings_service import get_setting

# --------------------------------------------------------------------- checks


@dataclass
class CheckResult:
    check: str
    ok: bool
    severity: IncidentSeverity
    detail: str
    data: dict[str, Any] = field(default_factory=dict)
    # allow-listed recovery action to attempt when this check fails
    recovery: str | None = None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def check_backup_freshness(db: Session) -> CheckResult:
    """Newest backup record must exist and respect the backup_max_age_hours SLO."""
    max_age_h = float(get_setting(db, "backup_max_age_hours", 26) or 26)
    newest = db.scalar(
        select(BackupRecord).order_by(BackupRecord.created_at_backup.desc()).limit(1)
    )
    if newest is None or newest.created_at_backup is None:
        return CheckResult(
            "backup_freshness", False, IncidentSeverity.CRITICAL,
            "no backup record exists — last-known-good restore impossible",
        )
    age_h = (_utcnow() - newest.created_at_backup).total_seconds() / 3600
    if age_h > max_age_h:
        return CheckResult(
            "backup_freshness", False, IncidentSeverity.CRITICAL,
            f"newest backup is {age_h:.1f}h old (SLO {max_age_h:.0f}h)",
            {"age_hours": round(age_h, 1), "storage_key": newest.storage_key},
        )
    return CheckResult(
        "backup_freshness", True, IncidentSeverity.LOW,
        f"newest backup {age_h:.1f}h old (SLO {max_age_h:.0f}h)",
    )


def check_notification_queue(db: Session) -> CheckResult:
    """PENDING notifications older than the warn age are a delivery backlog."""
    warn_min = float(get_setting(db, "monitor_queue_warn_age_minutes", 60) or 60)
    cutoff = _utcnow() - timedelta(minutes=warn_min)
    stuck = db.scalar(
        select(func.count())
        .select_from(NotificationOutbox)
        .where(NotificationOutbox.status == "PENDING", NotificationOutbox.created_at < cutoff)
    ) or 0
    if stuck:
        return CheckResult(
            "notification_queue", False, IncidentSeverity.HIGH,
            f"{stuck} notification(s) PENDING for more than {warn_min:.0f} minutes",
            {"stuck": stuck}, recovery="requeue_stuck_notifications",
        )
    return CheckResult("notification_queue", True, IncidentSeverity.LOW, "queue healthy")


def check_job_queue(db: Session) -> CheckResult:
    """PENDING jobs past run_at by more than the stuck threshold need a retry."""
    stuck_min = float(get_setting(db, "monitor_job_stuck_minutes", 30) or 30)
    cutoff = _utcnow() - timedelta(minutes=stuck_min)
    stuck = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.status == "PENDING", Job.run_at < cutoff)
    ) or 0
    if stuck:
        return CheckResult(
            "job_queue", False, IncidentSeverity.MEDIUM,
            f"{stuck} job(s) PENDING past run_at by more than {stuck_min:.0f} minutes",
            {"stuck": stuck}, recovery="requeue_stuck_jobs",
        )
    return CheckResult("job_queue", True, IncidentSeverity.LOW, "queue healthy")


def check_database(db: Session) -> CheckResult:
    """Connectivity plus ungranted (blocking) locks."""
    db.execute(text("SELECT 1"))
    blocking = db.scalar(text("SELECT count(*) FROM pg_locks WHERE NOT granted")) or 0
    if blocking:
        return CheckResult(
            "database_locks", False, IncidentSeverity.HIGH,
            f"{blocking} ungranted lock(s) — sessions are blocking each other",
            {"blocking_locks": blocking},
        )
    return CheckResult("database_locks", True, IncidentSeverity.LOW, "no blocking locks")


CHECKS = {
    "backup_freshness": check_backup_freshness,
    "notification_queue": check_notification_queue,
    "job_queue": check_job_queue,
    "database_locks": check_database,
}

# ------------------------------------------------------- safe recovery allow-list


def _requeue_stuck_jobs(db: Session) -> int:
    """Idempotent: PENDING jobs that are due get run_at=now (workers retry)."""
    stuck_min = float(get_setting(db, "monitor_job_stuck_minutes", 30) or 30)
    cutoff = _utcnow() - timedelta(minutes=stuck_min)
    rows = db.scalars(
        select(Job).where(Job.status == "PENDING", Job.run_at < cutoff)
    ).all()
    now = _utcnow()
    for job in rows:
        job.run_at = now
    return len(rows)


def _requeue_stuck_notifications(db: Session) -> int:
    """Idempotent: the outbox dedupes by idempotency_key, so resetting the
    next attempt of a stuck PENDING row is a safe retry, never a duplicate."""
    warn_min = float(get_setting(db, "monitor_queue_warn_age_minutes", 60) or 60)
    cutoff = _utcnow() - timedelta(minutes=warn_min)
    rows = db.scalars(
        select(NotificationOutbox).where(
            NotificationOutbox.status == "PENDING", NotificationOutbox.created_at < cutoff
        )
    ).all()
    now = _utcnow()
    for row in rows:
        row.next_attempt_at = now
    return len(rows)


# EXHAUSTIVE allow-list: docs/20 "AI may … retry idempotent jobs". Anything
# not here is refused — there is intentionally no code path for data
# deletion, auth/policy changes, DNS/credential rotation, schema changes,
# production deploys or paid capacity.
RECOVERY_ACTIONS = {
    "requeue_stuck_jobs": _requeue_stuck_jobs,
    "requeue_stuck_notifications": _requeue_stuck_notifications,
}


def run_recovery_action(db: Session, name: str) -> int:
    """Execute one allow-listed recovery action. Unknown names are refused."""
    action = RECOVERY_ACTIONS.get(name)
    if action is None:
        raise ConflictError(
            f"recovery action '{name}' is not in the allow-list {sorted(RECOVERY_ACTIONS)} "
            "(docs/20: only idempotent requeues may run autonomously)"
        )
    return action(db)


def _recovery_actions_last_hour(db: Session) -> int:
    """Circuit-breaker window: RECOVERY timeline events in the past hour."""
    cutoff = _utcnow() - timedelta(hours=1)
    total = 0
    for timeline in db.scalars(select(Incident.timeline)).all():
        for entry in timeline or []:
            ts = entry.get("ts", "")
            if entry.get("event") == "RECOVERY" and ts >= cutoff.isoformat():
                total += 1
    return total


# ---------------------------------------------------------------- lifecycle


def _timeline_entry(event: str, **kwargs: Any) -> dict[str, Any]:
    return {"ts": _utcnow().isoformat(), "event": event, **kwargs}


def _open_incident_for(db: Session, check: str) -> Incident | None:
    prefix = f"[{check}]"
    return db.scalar(
        select(Incident)
        .where(
            Incident.status.in_(
                [IncidentStatus.OPEN.value, IncidentStatus.INVESTIGATING.value,
                 IncidentStatus.MITIGATED.value]
            ),
            Incident.description.like(f"{prefix}%"),
        )
        .order_by(Incident.detected_at.desc())
        .limit(1)
    )


def _internal_tenant_id(db: Session) -> uuid.UUID:
    row = db.execute(text("SELECT id FROM tenants ORDER BY created_at LIMIT 1")).scalar_one_or_none()
    if row is None:
        raise ConflictError("No tenant exists — run init-db first")
    return row


def _handle_result(db: Session, result: CheckResult, tenant_id: uuid.UUID) -> dict[str, Any]:
    incident = _open_incident_for(db, result.check)
    if result.ok:
        if incident is not None:
            incident.status = IncidentStatus.RESOLVED.value
            incident.resolved_at = _utcnow()
            incident.timeline = [
                *(incident.timeline or []),
                _timeline_entry("RESOLVED", check=result.check, detail=result.detail),
            ]
            notify_admin(
                db,
                template_key="incident.resolved",
                payload={"check": result.check, "title": incident.title},
                idempotency_key=f"incident:{incident.id}:resolved",
                tenant_id=tenant_id,
            )
        return {"ok": True, "severity": result.severity.value,
                "incident_id": str(incident.id) if incident else None, "recovery": None}

    if incident is None:
        incident = Incident(
            tenant_id=tenant_id,
            title=f"Monitor: {result.check} failing",
            description=f"[{result.check}] {result.detail}",
            severity=result.severity.value,
            status=IncidentStatus.OPEN.value,
            timeline=[_timeline_entry("DETECTED", detail=result.detail, data=result.data)],
        )
        db.add(incident)
        db.flush()
        notify_admin(
            db,
            template_key="incident.opened",
            payload={"check": result.check, "severity": result.severity.value,
                     "detail": result.detail},
            idempotency_key=f"incident:{incident.id}:opened",
            tenant_id=tenant_id,
        )
    else:
        incident.timeline = [
            *(incident.timeline or []),
            _timeline_entry("RE_DETECTED", detail=result.detail, data=result.data),
        ]
        if result.severity.value != incident.severity:
            incident.timeline[-1]["event"] = "ESCALATED"
            incident.timeline[-1]["from_severity"] = incident.severity
            incident.severity = result.severity.value

    recovery_note = None
    if result.recovery is not None:
        breaker_cap = int(get_setting(db, "recovery_actions_max_per_hour", 5) or 5)
        if _recovery_actions_last_hour(db) >= breaker_cap:
            incident.timeline = [
                *(incident.timeline or []),
                _timeline_entry("RECOVERY_SKIPPED", action=result.recovery,
                                reason=f"circuit breaker: {breaker_cap}/h cap reached"),
            ]
            recovery_note = "skipped (circuit breaker)"
        else:
            count = run_recovery_action(db, result.recovery)
            incident.recovery_actions = [
                *(incident.recovery_actions or []),
                {"action": result.recovery, "count": count,
                 "ts": _utcnow().isoformat()},
            ]
            incident.timeline = [
                *(incident.timeline or []),
                _timeline_entry("RECOVERY", action=result.recovery, count=count),
            ]
            recovery_note = f"{result.recovery} ({count} item(s))"
    return {"ok": False, "severity": result.severity.value,
            "incident_id": str(incident.id), "recovery": recovery_note}


def run_monitor(db: Session) -> dict[str, dict[str, Any]]:
    """Run every check once; manage incidents; execute capped safe recovery."""
    tenant_id = _internal_tenant_id(db)
    summary: dict[str, dict[str, Any]] = {}
    for name, check in CHECKS.items():
        result = check(db)
        summary[name] = _handle_result(db, result, tenant_id)
    db.commit()
    return summary


# ------------------------------------------------------------- AI diagnosis


_REDACT_PATTERNS = [
    # specificity order: credentialed URLs before bare emails, so an email
    # embedded in https://user:pw@host is caught by the URL rule, not mangled
    (re.compile(r"https?://\S+@"), "[redacted-url-cred]"),
    (re.compile(r"\b(?:sk|pk|token|password|secret)[-_=:]\S+", re.IGNORECASE), "[redacted-credential]"),
    (re.compile(r"\b[0-9a-f]{32,}\b", re.IGNORECASE), "[redacted-hash]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[redacted-email]"),
]


def redact(text: str) -> str:
    """Strip emails, credentials, long hashes and credentialed URLs (docs/20)."""
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def diagnose_incident(db: Session, incident_id: uuid.UUID) -> dict[str, Any]:
    """AI diagnosis through the governed free-provider pool (fail-closed).

    The proposal lands in the timeline as an AI_DIAGNOSIS entry; it never
    executes actions — execution stays within the recovery allow-list.
    """
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise ConflictError(f"incident {incident_id} not found")

    context = redact(
        f"Incident: {incident.title}\n"
        f"Severity: {incident.severity}\nStatus: {incident.status}\n"
        f"Description: {incident.description}\n"
        f"Timeline events: {len(incident.timeline or [])}\n"
        f"Recovery actions so far: {incident.recovery_actions or 'none'}"
    )
    from app.modules.ai.inference import llm_complete

    result = llm_complete(
        db,
        tenant_id=incident.tenant_id,
        task="summarization",
        prompt=(
            "You are the on-call assistant for a small operations platform. "
            "Summarize the incident below in 3-5 sentences and propose at most "
            "two remediation steps an operator could take manually. Do not "
            "propose deleting data, changing auth policy, rotating DNS or "
            "credentials, schema changes, production deploys or paid capacity.\n\n"
            f"{context}"
        ),
    )
    if result.status != "SUCCEEDED":
        incident.timeline = [
            *(incident.timeline or []),
            _timeline_entry("AI_DIAGNOSIS", status=result.status, reason=result.reason),
        ]
        db.commit()
        return {"status": result.status, "reason": result.reason}

    diagnosis = redact(result.text)
    incident.status = IncidentStatus.INVESTIGATING.value
    incident.timeline = [
        *(incident.timeline or []),
        _timeline_entry("AI_DIAGNOSIS", status="SUCCEEDED", summary=diagnosis),
    ]
    db.commit()
    return {"status": "SUCCEEDED", "diagnosis": diagnosis}
