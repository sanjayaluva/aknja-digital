# Requirements Traceability Matrix

| Requirement group | Spec | Implementation module | Required evidence |
|---|---|---|---|
| Governance/AI | `.aknja/SYSTEM.md` | policy, orchestrator, tool gateway | bypass/self-approval tests |
| Service hierarchy | `source_service_hierarchy.md` | catalog, blueprint engine | taxonomy import and CRUD tests |
| Zero-cost | source v5.3.1 | quota service, admission controller | paid path blocked, stale quota fail-closed |
| Provider pools | source v5.3.2 | provider registry/scheduler | category failover tests |
| SDLC | Master SRS | projects/tasks/releases | lifecycle transition tests |
| Visual QA | `docs/16_QA_AND_VISUAL_VERIFICATION.md` | test runner/evidence | screenshots + comparison report |
| Staging | `docs/18_STAGING_RUNBOOK.md` | environment manager | provision/test/cleanup drill |
| Production | `docs/19_PRODUCTION_HOSTING.md` | hosting manager | deploy/rollback/restore evidence |
| Monitoring | `docs/20_PRODUCTION_OPERATIONS.md` | telemetry/incident | alert + incident drill |
| Data lifecycle | `docs/22_BACKUP_AND_DR.md` | backup/restore | restore drill report |
| Security | `docs/23_SECURITY_AND_PRIVACY.md` | auth, storage, tool gateway | ASVS-oriented test evidence |
| Commercial | `docs/24_COMMERCIAL_AND_BILLING.md` | quotes/contracts/invoices | financial reconciliation tests |

A traceability record must link requirement ID → implementation PR → test ID → evidence artifact → release ID.
