# Optional Managed Production Hosting

## Commercial gate
Client requests hosting → scope and capacity review → quote → signed hosting agreement → client approval of data location/terms → provision.

## Per-project isolation
- unique Compose project and network;
- dedicated service accounts and secret references;
- separate DB/user or dedicated database instance;
- persistent volumes with quotas;
- reverse-proxy hostname and TLS;
- CPU, memory, PID and storage limits;
- per-project logs/metrics and backup policy;
- no direct public DB port.

## Admission control
Estimate peak RAM/CPU, DB connections, storage growth, egress, backups and support load. Reserve host headroom for OS, Aknja control plane, monitoring and recovery. Run load test and failure test. Reject or require a separate VM when measured capacity is insufficient. Never infer safe application count from container count.

## Release
Promote the exact staging-approved digest. Verify config/secrets, DNS, TLS, migration and backup. Require approval bound to exact digest and destination. Run smoke tests and record release.

## SLA
Do not promise high availability from a single VM. Define availability, maintenance windows, response targets, backup retention, RPO/RTO, support hours, exclusions and client responsibilities in contract only after capacity and recovery drills validate them.
