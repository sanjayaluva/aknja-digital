# Staging Deployment Runbook

Preconditions: approved build digest, staging capacity, isolated test DB, secrets, DNS/preview method, migration plan.

1. Reserve staging resources.
2. Create isolated Compose project/network/volumes.
3. Pull exact image digest.
4. Apply backward-compatible migrations.
5. Start services and wait for readiness.
6. Run smoke tests, E2E, visual checks, security scans.
7. Publish restricted preview URL.
8. Record test evidence and UAT checklist.
9. Client tests and submits feedback.
10. Fixes return through CI and a new artifact; repeat staging.
11. On acceptance, freeze release record and prepare production handoff.
12. Archive evidence; cleanup temporary resources under retention policy.

Rollback staging by redeploying prior digest and restoring only test data if necessary. Never point staging at production DB.
