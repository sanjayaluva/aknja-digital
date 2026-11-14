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
