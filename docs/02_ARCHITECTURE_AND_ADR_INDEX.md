# Architecture Baseline and ADR Index

Approved baseline for implementation planning:
- Modular monolith.
- FastAPI + SQLAlchemy + Alembic + PostgreSQL + Pydantic v2.
- HTMX/Alpine/HTML/CSS frontend baseline.
- Docker Compose; no Kubernetes in initial release.
- One Central AI Orchestrator + dynamic scoped specialist capabilities.
- PostgreSQL is live state; Git is versioned source of truth.
- Temporary reusable staging; optional persistent production hosting.
- Zero-cost-first quota-aware external compute.

ADRs:
- `adr/ADR-001-backend-stack.md`
- `adr/ADR-002-execution-and-agent-model.md`
- `adr/ADR-003-environments-and-deployment.md`
- `adr/ADR-004-resource-and-zero-cost-policy.md`
- `adr/ADR-005-production-hosting-and-operations.md`
- `adr/ADR-006-data-and-memory.md`
- `adr/ADR-007-sync-sqlalchemy.md`

These decisions are the implementation baseline. Any change requires a new ADR and compatibility review.
