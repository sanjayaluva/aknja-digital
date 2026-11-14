# Implementation Status — Core Platform Implemented (v0.1.0)

**Last updated:** 14 November 2026 · see `docs/41_LOCAL_DEVELOPMENT_AND_TEST_RUNBOOK.md` for reproduction steps.

Evidence rule (unchanged): a status changes only with tests, commands and their output — never intention or a container start.

| Area | Status | Evidence |
|---|---|---|
| Requirements and architecture | SPECIFIED | Approved ADRs 001–007; traceability review pending |
| FastAPI application | IMPLEMENTED | `app/` modular monolith; 102 routes; `/health/live`, `/health/ready` verified against PostgreSQL; `tests/` suite |
| Authentication/RBAC/tenant isolation | IMPLEMENTED + TESTED | `tests/test_auth_rbac.py` — login/lockout/CSRF, deny-by-default RBAC, cross-tenant 404s, portal scoping (14 tests) |
| Central AI Orchestrator | IMPLEMENTED + TESTED | `app/modules/ai/orchestrator.py` state machine; `tests/test_tool_gateway.py` — illegal transitions, no COMPLETED without verification evidence, emergency stop |
| Tool Gateway | IMPLEMENTED + TESTED | `tests/test_tool_gateway.py` — allow-list, schema, RESTRICTED data block, approval-hash binding, no self-approval, idempotent replay, tenant scope |
| Service Catalog | IMPLEMENTED + TESTED | Full source taxonomy preserved: 19 families, 76 subcategories, 224 leaf services; truthful availability/readiness; `tests/test_lifecycles.py` |
| Resource/Quota Orchestrator | IMPLEMENTED + TESTED | `tests/test_quota.py` — ZERO_COST_ONLY rejects paid/unverified; stale/unknown quota fails closed; 95% hard-stop; concurrent reservations cannot oversubscribe (row-lock); circuit breaker; free-pool failover |
| Commercial lifecycle | IMPLEMENTED + TESTED | `tests/test_lifecycles.py` — lead→client→proposal→contract→scope freeze→30/30/40 invoices→manual payment reconciliation→PAID |
| Project delivery + gates | IMPLEMENTED + TESTED | STAGING_UAT requires active preview; PRODUCTION_HANDOFF requires accepted UAT; tasks require REVIEW→VERIFIED→DONE |
| Zero-hardcode system settings | IMPLEMENTED + TESTED | 43 seeded settings (SRS §8.2 Tabs 1–7); typed validation; audit on save; protected keys not runtime-editable |
| Audit ledger | IMPLEMENTED + TESTED | Hash-chained, content-recomputing verification; DB-level append-only trigger (UPDATE/DELETE raise); tamper detection test |
| Admin UI + client portal | IMPLEMENTED | 12 admin screens + portal (projects, milestones, staging previews, feedback, UAT, invoices); server-rendered HTMX/Alpine; `tests/test_ui.py` (18 tests) |
| Project workspace/staging | PARTIAL | Preview-link lifecycle, evidence and cleanup models implemented; Compose-based staging provisioning requires a Docker host (design in docs/15) |
| Production hosting | SPECIFIED, OPTIONAL | Not deployed. Requires capacity admission, backup/restore drills and contract per docs/19, docs/38 |
| QA/visual verification | PARTIAL | Unit/integration/contract tests: 80 passing against real PostgreSQL 16. Playwright E2E + visual comparison: not yet wired (docs/16) |
| Client portal UAT workflow | IMPLEMENTED + TESTED | Portal tests in `tests/test_ui.py`, `tests/test_auth_rbac.py` |
| Production incident automation | SPECIFIED | Incident/support/backup models + UI-ready; automation deferred (docs/20) |

**Test suite:** 80 tests, all passing (`pytest -q`), including concurrency tests against real PostgreSQL. Lint: `ruff check app tests` clean.

**Not claimed:** live provider accounts verified in the actual console — the documented candidate pool (21 providers across 8 categories) is seeded as FREE_UNVERIFIED/disabled via `register-provider-candidates`, and activation requires the audited `verify-provider` step (docs/33 worksheet; implemented and tested in `tests/test_provider_candidates.py`). Staging/production deployment, Playwright E2E, provider adapters verified against live accounts (all external providers remain disabled until account verification per SRS §14), Telegram delivery (integration stub present, token unset).
