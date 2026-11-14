# Observability and SRE

Structured logs must include request/job/project/environment identifiers and redact secrets/PII. Metrics include API latency/error rate, job queue age, worker utilization, resource consumption, quota freshness, database health, disk, TLS expiry, backup age, deployment health and incident MTTR.

Define thresholds after baseline measurement. Each alert has severity, deduplication key, runbook, notification target and escalation policy. Keep dead-letter queues and retry exhaustion visible. Produce incident postmortems for major incidents. Do not display synthetic demo metrics as live telemetry.
