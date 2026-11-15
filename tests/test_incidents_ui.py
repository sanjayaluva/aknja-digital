"""Admin incidents console (docs/20 Phase 8 UI): list, detail, operator close.

The lifecycle itself is monitor-driven (tests/test_monitor.py); these tests
cover the operator surface: rendering, cross-tenant denial, CSRF, close.
"""

from __future__ import annotations

from sqlalchemy import select

from app.modules.governance.models import AuditEvent
from app.modules.ops.models import BackupRecord, Incident, Job
from tests.conftest import make_tenant

# ------------------------------------------------------------------ rendering


def test_incidents_page_empty_state(db, seed, admin_client) -> None:
    resp = admin_client.get("/admin/incidents")
    assert resp.status_code == 200
    assert "Incidents" in resp.text
    assert "No incidents" in resp.text


def test_monitor_incident_visible_in_list(db, seed, admin_client) -> None:
    from app.modules.ops.monitor import run_monitor

    run_monitor(db)  # no backup record -> CRITICAL incident

    resp = admin_client.get("/admin/incidents")
    assert resp.status_code == 200
    assert "Monitor: backup_freshness failing" in resp.text
    assert "CRITICAL" in resp.text
    assert "1 active incident" in resp.text


def test_incident_detail_shows_timeline_and_recovery(db, seed, admin_client) -> None:
    from datetime import UTC, datetime

    from app.modules.ops.monitor import run_monitor

    db.add(BackupRecord(  # keep unrelated checks green
        tenant_id=seed.tenant.id, scope="DATABASE", storage_key="ui.backup",
        checksum="x" * 64, size_bytes=1, encrypted=False,
        created_at_backup=datetime.now(UTC),
    ))
    db.add(Job(tenant_id=seed.tenant.id, kind="ui.requeue", payload={},
               run_at=datetime(2026, 1, 1, tzinfo=UTC)))
    db.commit()
    run_monitor(db)
    incident = db.scalar(
        select(Incident).where(Incident.description.like("[job_queue]%"))
    )

    resp = admin_client.get(f"/admin/incidents/{incident.id}")
    assert resp.status_code == 200
    assert "requeue_stuck_jobs" in resp.text          # recovery table
    assert "DETECTED" in resp.text                    # timeline events
    assert "RECOVERY" in resp.text


def test_anonymous_redirected_to_login(client) -> None:
    resp = client.get("/admin/incidents", follow_redirects=False)
    assert resp.status_code == 302


# ------------------------------------------------------------------- actions


def test_incident_close_flow_records_timeline_and_audit(db, seed, admin_client) -> None:
    from app.modules.ops.monitor import run_monitor

    run_monitor(db)
    incident = db.scalar(select(Incident))
    assert incident.status == "OPEN"

    resp = admin_client.post(
        f"/admin/incidents/{incident.id}/close",
        data={"note": "noise during deploy", "csrf_token": admin_client.csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db.expire_all()
    incident = db.scalar(select(Incident).where(Incident.id == incident.id))
    assert incident.status == "CLOSED"
    assert incident.resolved_at is not None
    assert incident.timeline[-1]["event"] == "CLOSED_BY_OPERATOR"
    assert incident.timeline[-1]["note"] == "noise during deploy"

    audit = db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "incident.closed",
            AuditEvent.resource_id == str(incident.id),
        )
    )
    assert audit is not None

    # monitor dedupe ignores CLOSED: a fresh failure opens a NEW incident
    from app.modules.ops.monitor import run_monitor as rerun

    rerun(db)
    assert len(db.scalars(select(Incident)).all()) == 2


def test_close_rejects_bad_csrf(db, seed, admin_client) -> None:
    from app.modules.ops.monitor import run_monitor

    run_monitor(db)
    incident = db.scalar(select(Incident))

    # missing form field -> FastAPI validation rejects before the handler
    resp = admin_client.post(
        f"/admin/incidents/{incident.id}/close",
        data={"note": "no csrf"},
        follow_redirects=False,
    )
    assert resp.status_code == 422

    # present but wrong value -> csrf_guard 403
    resp = admin_client.post(
        f"/admin/incidents/{incident.id}/close",
        data={"note": "forged", "csrf_token": "forged-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    db.expire_all()
    assert db.scalar(select(Incident).where(Incident.id == incident.id)).status == "OPEN"


def test_cross_tenant_incident_is_404(db, seed, admin_client) -> None:
    other = make_tenant(db, "Other Corp", "other-corp")
    incident = Incident(
        tenant_id=other.id,
        title="Someone else's incident",
        description="[backup_freshness] not yours",
        severity="CRITICAL",
    )
    db.add(incident)
    db.commit()

    resp = admin_client.get(f"/admin/incidents/{incident.id}")
    assert resp.status_code == 404
    resp = admin_client.post(
        f"/admin/incidents/{incident.id}/close",
        data={"csrf_token": admin_client.csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 404
