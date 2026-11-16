# Episodic memory — Incident automation: monitor + safe recovery (T-013, 2026-11-15)

**Scope:** EPISODIC · **Sensitivity:** INTERNAL · **Approved:** yes (founder-reviewed)

## What was built

The Phase 8 automation core of docs/20, meeting the roadmap exit criteria
(injected failure detected · safe recovery verified · unsafe action blocked):

**`app/modules/ops/monitor.py`**
- Checks: backup freshness (reuses the T-010 `backup_max_age_hours` SLO — CRITICAL
  when no record or stale, and deliberately NO auto-recovery: backups need an
  operator), notification-queue age (HIGH, requeue), job-queue stuck (MEDIUM,
  requeue), DB blocking locks (HIGH, no auto-action).
- Lifecycle: dedupe via `[<check>]` description prefix against OPEN-ish
  incidents; timeline JSONB events DETECTED / RE_DETECTED / ESCALATED /
  RESOLVED / RECOVERY / RECOVERY_SKIPPED / AI_DIAGNOSIS; founder notified
  through the durable outbox with per-incident idempotency keys
  (`incident:{id}:opened|:resolved`).
- Safety: `RECOVERY_ACTIONS` is an exhaustive two-entry allow-list
  (`requeue_stuck_jobs`, `requeue_stuck_notifications`) — both idempotent by
  construction (jobs re-due, outbox dedupes on idempotency_key, only
  next_attempt_at moves). `run_recovery_action` raises ConflictError for
  anything else; the docs/20 forbidden class has no code path. Circuit
  breaker caps autonomous actions per rolling hour (setting, default 5).
- AI diagnosis: `diagnose_incident` builds a redacted context (emails,
  credentials, long hashes, credentialed URLs — pattern order matters:
  URL-cred before email, or emails inside URLs get mangled) and calls the
  governed `llm_complete` (summarization profile). Fail-closed: without a
  verified provider it records PENDING_MANUAL (live-smoked: reason
  "AI_PROVIDER_ENABLED=false"). Proposals land in the timeline; execution
  stays allow-listed.

Settings: `monitor_queue_warn_age_minutes` (60),
`monitor_job_stuck_minutes` (30), `recovery_actions_max_per_hour` (5) —
seeded on the ops_recovery tab (49 settings now).
CLI: `aknja monitor run`, `aknja monitor diagnose <id>`.

## Verification

171/171 tests (11 new), ruff clean, dependency audit clean
(81/0/0/0/0). Live CLI smoke on a migrated+seeded scratch DB: detection
CRITICAL + one incident + one outbox row → second run dedupes (same id) →
diagnose fail-closed.

## Follow-ups surfaced

- Admin UI listing for incidents (models are UI-ready; no `/admin/incidents`
  screen yet) — next UI round candidate.
- Monitor is CLI/cron-triggered; a scheduler (or CI cron) invoking
  `aknja monitor run` is a deploy-time decision (docs/19).

## Sandbox lesson

`$( cmd & echo $! )` kills the background job when the substitution subshell
exits — which stopped the pgserver cluster mid-smoke. Plain `cmd &` in the
main shell survives; the smoke script (`scripts/monitor_smoke.sh` in the
sandbox workspace) uses a marker + `pkill -f` for cleanup. Also:
`pgrep -f pattern` matches the invoking shell's own command line — use a
regex bracket (`pat[t]ern`) to avoid self-matches.
