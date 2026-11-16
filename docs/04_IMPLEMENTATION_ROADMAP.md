# Implementation Roadmap

## Phase 0 — Repository and engineering foundation (P0)
Status: ✅ exit met — clean clone boots, CI green, migrations run, no secrets committed.
- Create repository structure and branch protection.
- Pin Python/runtime/dependencies/container base images.
- FastAPI app factory, config validation, health endpoints.
- PostgreSQL, SQLAlchemy, Alembic, structured logging.
- CI lint/type/unit/secret scan.
- Protected governance and audit primitives.
**Exit:** clean clone boots; CI passes; migrations run; no secrets committed.

## Phase 1 — Identity, tenancy and core operations (P0)
Status: ✅ exit met — cross-tenant denial proven by tests (T-001).
- Super Admin auth, MFA-ready design, sessions, RBAC.
- Clients, contacts, projects, requirements, milestones, tasks, artifacts.
- Tenant isolation tests.
- Immutable audit events.
**Exit:** authorization tests prove cross-tenant access denied.

## Phase 2 — Service catalog and commercial lifecycle (P0/P1)
Status: ✅ exit met — quoting gated on truthful availability/readiness (T-001).
- Import full service taxonomy.
- Service blueprints, availability/readiness, capability/tool requirements.
- Packages, pricing rules, custom quotes, proposals, contracts, scope freeze/change requests.
- Invoice and manual payment reconciliation.
**Exit:** service can be quoted only with truthful availability and readiness.

## Phase 3 — AI orchestration and Tool Gateway (P1)
Status: ✅ exit met — permission-bypass and self-approval tests pass; provider abstraction live (inference layer + orchestrator LLM steps, T-004/T-005).
- Capability registry, plan/task graph, worker dispatch, structured output.
- Policy engine, short-lived permits, approval payload hashing.
- Provider abstraction; no provider required for baseline workflow.
**Exit:** permission bypass and self-approval tests pass.

## Phase 4 — Resource and quota management (P1)
Status: ✅ implemented + tested — registry, ledger, snapshots, atomic reservation, hard stop, failover (T-002).
- Provider registry, usage events, quota snapshots, reservations, reconciler.
- Admission controller, circuit breakers, category pools.
- Free-only enforcement and stale-metric fail-closed.
**Exit:** paid path cannot execute; concurrent reservation cannot oversubscribe.

## Phase 5 — Development workspace and QA (P1)
Status: ◐ partial — unit/integration/contract suite (101 tests) on real PostgreSQL; Playwright/visual pending (T-007).
- Git integration, CI artifacts, isolated workspace, test runner.
- Playwright E2E, screenshot evidence, visual comparison, security scans.
- Build-once artifact registry.
**Exit:** sample web project passes all gates with stored evidence.

## Phase 6 — Reusable staging and client portal (P1)
Status: ◐ partial — portal UAT workflow done; Compose staging provisioning pending, host rebased to OCI Always-Free ARM (SRS §2.1 erratum).
- Compose-based temporary staging projects, restricted preview URLs.
- UAT feedback, bug reports, revision tracking, acceptance records.
- Cleanup with retained evidence.
**Exit:** staging provision/cleanup is repeatable and safe.

## Phase 7 — Optional managed production hosting (P2)
Status: ○ specified, not deployed (docs/19, docs/38).
- Host inventory, capacity admission, tenant Compose projects, reverse proxy.
- TLS, secrets, DB, persistent volumes, backup, restore, deployment approvals.
- Billing/subscription and contract linkage.
**Exit:** at least one non-critical pilot app passes backup restore and deployment rollback drills.

## Phase 8 — Monitoring, incidents and maintenance (P2)
Status: ○ models + UI-ready, automation deferred (docs/20).
- Metrics, logs, alerts, incident workflow, runbooks.
- AI diagnosis and fix branch workflow.
- Safe recovery allow-list; approval gates.
**Exit:** injected failure detected; safe recovery verified; unsafe action blocked.

## Phase 9 — Digital marketing and advanced capabilities (P2/P3)
Status: ○ future (docs/25).
- SEO, content, creative, analytics, messaging and ads modules.
- Official APIs and client authorization.
- Audio/video batch processing and external GPU adapters.
- Mobile/desktop/IoT/advanced data engineering capabilities as partner/tooling readiness permits.
**Exit:** each service family passes its own capability evaluation before `READY`.
