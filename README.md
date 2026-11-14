# Aknja Digital v6.1 — Final Development & Deployment Documentation

**Status:** Core platform implemented and tested (see `.aknja/STATUS.md` for the evidence table). Staging/production deployment and live provider verification remain open work.  
**Business:** Aknja Digital | Legal/billing entity: Aknja Software Solutions  
**Repository target:** `aknja-digital` (private)  
**Default client presentation:** `solo_developer`  
**Default cost mode:** `ZERO_COST_ONLY`  
**Primary delivery responsibility:** verified development + QA + reusable staging + client UAT.  
**Optional commercial services:** Aknja-managed production hosting, monitoring, backup, maintenance and support.

## What is implemented

A modular-monolith FastAPI platform (ADR-001/007) with:

- **Identity & tenancy** — session auth (argon2id), CSRF, 7 roles, deny-by-default RBAC, tenant-scoped queries, portal users bound to a single client.
- **Governance** — hash-chained append-only audit ledger (DB-trigger enforced), HITL approvals bound to exact payload hashes (no self-approval, no SYSTEM_WORKER approvals), founder-only emergency stop.
- **CRM & commercial lifecycle** — leads → qualification → proposals → contracts → scope freeze → change requests → milestone invoices (30/30/40 split from settings) → manual payment reconciliation.
- **Service catalog** — the complete preserved source taxonomy (19 families, 76 subcategories, 224 services) with independent availability/readiness; quoting is blocked unless truthfully sellable.
- **Delivery** — project lifecycle state machine with gates (staging preview required for UAT, accepted UAT required for handoff), milestones, tasks (VERIFIED before DONE), artifacts, feedback, UAT records, expiring staging preview links.
- **AI orchestration** — capability registry (10 templates), run state machine, Tool Gateway enforcing actor/tenant/scope/allow-list/schema/classification/approval-hash/quota/idempotency/rate-limit with audit before/after. Zero external providers needed for core operation.
- **Resource plane** — provider registry, quota snapshots, atomic row-locked reservations, 95% hard-stop, stale/unknown fail-closed, circuit breakers, category-based free-pool failover, ZERO_COST_ONLY guard.
- **Zero-hardcode settings** — 43 seeded business parameters (SRS §8.2) editable in `/admin/settings` with type validation, audit and cache invalidation; protected invariants are not runtime-editable.
- **UI** — dark operations console (12 screens) + client portal, server-rendered HTML + HTMX + Alpine.js with vendored assets (no CDN dependency).

## Start here

1. Read `.aknja/README.md`, `.aknja/SYSTEM.md`, `.aknja/STATUS.md`.
2. Read `docs/01_MASTER_SRS_V6.1.md`.
3. Read `docs/02_ARCHITECTURE_AND_ADR_INDEX.md` and all `docs/adr/`.
4. **Run the platform locally:** `docs/41_LOCAL_DEVELOPMENT_AND_TEST_RUNBOOK.md` (bootstrap → migrate → seed → verify-install → run).
5. Implement further phases in the order in `docs/04_IMPLEMENTATION_ROADMAP.md`.
6. Use `docs/05_REQUIREMENTS_TRACEABILITY.md` to map requirements to tests and evidence.
7. Use `docs/06_RELEASE_AND_ENVIRONMENT_MODEL.md` for local → CI → staging → UAT → optional production.

## Quick start

```bash
pip install -e ".[dev]"
cp .env.example .env           # set SECRET_KEY + DATABASE_URL
alembic upgrade head
python -m app.cli create-super-admin --email founder@aknja.pp.ua
python -m app.cli seed && python -m app.cli import-taxonomy && python -m app.cli verify-install
uvicorn app.main:app --reload  # /admin · /portal · /api/docs · /health/ready
pytest -q                      # 80 tests against real PostgreSQL
```

## Important status statement

The core application is implemented and covered by tests (see `.aknja/STATUS.md`). It has **not** been deployed to staging or production, and no live provider accounts, quotas, secrets, OCI tenancy quotas, domains, or production capacity have been inspected or verified. Provider entries remain candidates until verified in the actual account. Playwright E2E, visual verification and live Telegram delivery are specified but not yet wired.

## Technology baseline

Single backend: **FastAPI + SQLAlchemy 2.x (sync, ADR-007) + Alembic + PostgreSQL + Pydantic v2**. Frontend: server-rendered HTML + HTMX + Alpine.js with a hand-rolled design system (no external CDN). Docker Compose is the deployment unit. Kubernetes is deferred until measured scale requires it.

## Source preservation

- `docs/source_master_srs_v5.3_original.md` preserves the supplied v5.3 master baseline verbatim.
- `docs/source_zero_cost_guard_v5.3.1.md` preserves the detailed Zero-Cost Guard.
- `docs/source_provider_pools_v5.3.2.md` preserves the detailed provider pool/failover specification.
- `docs/source_service_hierarchy.md` transcribes the user-supplied Service Hierarchy & Deliverables Matrix (imported verbatim into the catalog).
- v6.1 amendments clarify, extend or explicitly supersede conflicting legacy assumptions. Do not silently delete original requirements.

## Package boundaries

- `.aknja/`: versioned AI/development intelligence, governance, decisions, capability templates and reviewed memory.
- `app/`: application source (modular monolith: `core/`, `modules/`, `api/`, `ui/`, `templates/`, `static/`).
- `alembic/`: authoritative database migrations.
- `database/`: legacy starter schema reference (superseded by Alembic).
- `infra/`: deployment templates and scripts.
- `docs/`: human-readable product, engineering and operational documentation.
- `tests/`: pytest suite (runs against real PostgreSQL).
- Secrets, client production data, raw database dumps, private keys and runtime logs must never be committed.
