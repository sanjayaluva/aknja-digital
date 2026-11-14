# Aknja Digital v6.1 — Final Development & Deployment Documentation

**Status:** Development handoff baseline; documentation and starter assets only.  
**Business:** Aknja Digital | Legal/billing entity: Aknja Software Solutions  
**Repository target:** `aknja-digital` (private)  
**Default client presentation:** `solo_developer`  
**Default cost mode:** `ZERO_COST_ONLY`  
**Primary delivery responsibility:** verified development + QA + reusable staging + client UAT.  
**Optional commercial services:** Aknja-managed production hosting, monitoring, backup, maintenance and support.

## Start here

1. Read `.aknja/README.md`, `.aknja/SYSTEM.md`, `.aknja/STATUS.md`.
2. Read `docs/01_MASTER_SRS_V6.1.md`.
3. Read `docs/02_ARCHITECTURE_AND_ADR_INDEX.md` and all `docs/adr/`.
4. Follow `docs/03_DEVELOPER_BOOTSTRAP.md`.
5. Implement in the order in `docs/04_IMPLEMENTATION_ROADMAP.md`.
6. Use `docs/05_REQUIREMENTS_TRACEABILITY.md` to map requirements to tests and evidence.
7. Use `docs/06_RELEASE_AND_ENVIRONMENT_MODEL.md` for local → CI → staging → UAT → optional production.

## Important status statement

This package is a detailed implementation specification plus starter configuration/templates. It is **not** an implemented, tested, deployed or production-certified application. No live provider accounts, quotas, secrets, OCI tenancy quotas, domains, or production capacity were inspected by generating this package. Provider entries are candidates until verified in the actual account.

## Technology baseline

Recommended single backend: **Fastapi + SQLAlchemy 2.x + Alembic + PostgreSQL + Pydantic v2**. Frontend baseline: server-rendered HTML + HTMX + Alpine.js + Tailwind CSS; avoid introducing a second backend framework. Docker Compose is the initial deployment unit. Kubernetes is deferred until measured scale requires it.

## Source preservation

- `docs/source_master_srs_v5.3_original.md` preserves the supplied v5.3 master baseline verbatim.
- `docs/source_zero_cost_guard_v5.3.1.md` preserves the detailed Zero-Cost Guard.
- `docs/source_provider_pools_v5.3.2.md` preserves the detailed provider pool/failover specification.
- `docs/source_service_hierarchy.md` transcribes the user-supplied Service Hierarchy & Deliverables Matrix.
- v6.1 amendments clarify, extend or explicitly supersede conflicting legacy assumptions. Do not silently delete original requirements.

## Package boundaries

- `.aknja/`: versioned AI/development intelligence, governance, decisions, capability templates and reviewed memory.
- `app/`: application source (created during implementation).
- `database/`: schema and migrations.
- `infra/`: deployment templates and scripts.
- `docs/`: human-readable product, engineering and operational documentation.
- Secrets, client production data, raw database dumps, private keys and runtime logs must never be committed.
