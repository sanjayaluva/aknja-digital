# Release and Environment Model

## Environment separation
- Local: synthetic data, developer secrets.
- CI: disposable DB, mocks, no production secrets.
- Staging: restricted URL, synthetic/test data, separate DB or isolated instance.
- Production: persistent client data, restricted access, backups, monitoring.

## Promotion
1. CI builds immutable artifact.
2. Artifact is scanned and receives digest/SBOM.
3. Deploy exact digest to staging.
4. Run smoke, functional, visual, security and performance checks.
5. Client UAT and founder acceptance.
6. Verify production backup and migration plan.
7. Super Admin approves exact release payload.
8. Deploy exact digest.
9. Run post-deploy smoke checks and monitor.
10. Roll back or forward-fix according to runbook.

Staging cleanup never deletes Git source, release artifact, evidence, client feedback or approval records.
