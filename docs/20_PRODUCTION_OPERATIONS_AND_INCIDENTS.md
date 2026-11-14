# Production Monitoring, Incidents and AI-Assisted Recovery

Monitor host CPU/RAM/disk/inodes, network, container health/restarts, HTTP status/latency, application exceptions, DB connections/locks/storage, queue depth/age/dead letters, TLS expiry, backup freshness, quota and provider health.

Incident lifecycle: detect → deduplicate → severity → notify → diagnose → mitigate → verify → root cause → corrective action → close/postmortem.

AI may:
- summarize alerts/logs with secrets redacted;
- correlate deploys and error rates;
- propose remediation;
- restart allow-listed stateless services;
- retry idempotent jobs;
- create a fix branch and tests;
- deploy to staging.

AI may not autonomously:
- delete/restore production data;
- alter auth/security policy;
- rotate DNS or credentials without approval;
- change schema destructively;
- deploy code to production;
- increase paid spend or provision paid capacity.

Use circuit breakers and rate limits to avoid runaway remediation loops.
