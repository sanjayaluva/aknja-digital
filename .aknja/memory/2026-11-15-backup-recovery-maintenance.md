# Episodic memory — Backup/restore + maintenance mode (2026-11-15)

**Scope:** EPISODIC · **Sensitivity:** INTERNAL · **Approved:** yes (founder-reviewed)

## What was built

The v5.3.2 §5A required-architecture pair (backlog H5):

**Backup pipeline** (`app/modules/ops/backup.py`): `create_backup` runs
pg_dump (custom format, `--no-owner --no-privileges`) from the bundled
pgserver toolchain (auto-discovered; `pg_bin_dir` setting overrides),
writes a sidecar manifest (sha256, size, per-table counts, alembic head)
and a `backup_records` row, audits `backup.created` and notifies the
founder. `verify_backup` checks sha256+size vs manifest plus a freshness
SLO (`backup_max_age_hours`, seeded 26h). `run_restore_drill` restores
into an isolated scratch database on the same cluster, verifies counts,
schema and the audit hash-chain on the RESTORED database, records duration
and `restore_drilled_at`, then drops the target — the artifact is only
ever opened read-only, so a failed drill cannot destroy the last known-good
backup. `prune_backups` deletes old artifacts but refuses to run when
fewer than one VERIFIED backup would remain; corrupt/missing artifacts are
pruned, never counted as good.

**Maintenance mode** (`app/modules/ops/maintenance.py` + middleware in
main.py): `maintenance_mode_enabled`/`maintenance_reason` settings;
`set_maintenance_mode` audits and founder-notifies exactly once per state
transition (re-asserting the same state is a no-op);
`MaintenanceModeMiddleware` returns 503 + Retry-After 30 + MAINTENANCE_MODE
envelope for every mutating request except `/api/v1/auth/login|logout`;
reads and /healthz stay up. The flag is read from the DB with a 5s TTL
cache — NOT the settings cache — because the settings cache is
process-local and a CLI toggle runs in another process.

CLI: `aknja backup create|verify|drill|prune`, `aknja maintenance
on|off|status` (nested argparse subparsers: space-separated subcommand
strings do NOT work as argparse choices).

## Lessons worth remembering

- **Postgres aborts the whole transaction on any statement error** — a
  `try/except` around `SELECT ... FROM alembic_version` swallows the
  exception but leaves the session poisoned; every later statement fails
  with InFailedSqlTransaction. Check `to_regclass('public.alembic_version')`
  first instead. Same class of bug hit twice in one round (backup create +
  drill verification).
- **`Base.metadata.sorted_tables` resolves FKs by name across the whole
  registry** — calling it from a module whose import chain hasn't pulled in
  every model (e.g. `projects` via delivery) raises NoReferencedTableError.
  Always `import app.models` before touching sorted_tables outside tests.
- pgserver's default `cleanup_mode="stop"` kills the daemon when the
  creating process exits — cross-process CLI smoke needs
  `get_server(pgdata, cleanup_mode=None)`.
- SQLAlchemy URL → libpq URI conversion must swap the scheme
  (`postgresql+psycopg://` → `postgresql://`), not delete a suffix:
  `url.replace("postgresql+", "postgresql")` produced `postgresqlpsycopg://`.
- Starlette `add_middleware` PREPENDS: the middleware added LAST is the
  OUTERMOST. Request-id/security-header middleware must be added last so
  freeze responses also get headers.

**Provenance:** this round's commit; `tests/test_backup_recovery.py` (7);
live CLI smoke evidence in TASK_LOG T-010; 160 tests passing, ruff clean;
docs/22 restore sequence.
