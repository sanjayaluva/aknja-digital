# Release, Rollback and Database Migration Runbook

Use expand/contract migrations:
1. add backward-compatible schema;
2. deploy code compatible with old/new schema;
3. backfill in bounded resumable batches;
4. verify row counts/checksums;
5. switch reads/writes;
6. remove obsolete schema in a later release after backup and approval.

Rollback:
- application rollback to prior image digest;
- database rollback only if migration is reversible and tested;
- otherwise forward-fix or restore from verified backup under approved maintenance window.
Never assume container rollback reverses data migration. Record exact migration revision, backup ID and release digest.
