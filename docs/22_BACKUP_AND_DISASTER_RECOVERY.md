# Backup and Disaster Recovery

RPO/RTO and retention are not invented in this package. Set them per hosting contract after workload and cost review.

Minimum design:
- DB backups plus object/file backups and a manifest;
- encryption at rest and in transit;
- off-host/offsite copy where available and contractually permitted;
- checksums and backup freshness monitoring;
- documented restore sequence;
- periodic restore drill to isolated environment;
- migration/rollback compatibility;
- client export and deletion workflow.

Replication is not backup. A backup is not proven until restored. Never overwrite the only known-good backup during a failed restore. Record restore duration and achieved data-loss window; use results to set RPO/RTO.

## Implemented restore sequence (T-010)

The platform ships the tooling for the minimum design above:

- `aknja backup create` — pg_dump custom-format artifact + sidecar manifest
  (sha256, size, per-table row counts, alembic head) + a `backup_records`
  row; audited (`backup.created`) and announced to the founder channel
  (`backup.completed`).
- `aknja backup verify [--max-age-hours N]` — checksum/size verification
  against the manifest; the freshness SLO default is the seeded
  `backup_max_age_hours` setting (26h).
- `aknja backup drill` — restore into an isolated scratch database on the
  same cluster, verify counts + schema + audit hash-chain, drop the target,
  record duration and `restore_drilled_at`. A failed drill never touches the
  artifact (opened read-only) and never overwrites a known-good backup.
- `aknja backup prune --keep N` — deletes old artifacts/records but refuses
  to run if fewer than one *verified* backup would remain; corrupt or
  missing artifacts are pruned, never kept as "good".
- `aknja maintenance on|off|status` — controlled write freeze (v5.3.2 §5A):
  mutating requests get 503 + Retry-After, reads and /healthz stay up, auth
  stays usable; activation is audited and notifies the founder. Toggle via
  CLI takes effect in the running server within ~5 seconds (TTL-cached DB
  read). Use this window for a verified restore/promotion when zero-loss
  replication is not available.

Off-host/offsite copy and at-rest encryption of the backup directory remain
hosting-environment steps (record in the runbook per contract); artifacts on
disk are not encrypted by the application.
