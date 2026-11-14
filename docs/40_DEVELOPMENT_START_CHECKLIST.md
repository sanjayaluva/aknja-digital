# Development Start Checklist

- [x] Private repository exists. (Branch protection: enable on GitHub settings — requires admin UI access.)
- [x] `.aknja/` structure committed.
- [x] FastAPI stack decision accepted and dependency versions pinned (ADR-001, ADR-007).
- [x] `.env.example` reviewed; real secrets stored outside Git.
- [x] Docker Compose local DB starts (compose.yaml db service).
- [x] Alembic initial migration runs (56 tables).
- [x] `/health/live` and `/health/ready` work (verified against PostgreSQL).
- [x] CI runs lint, tests, migration check, install verification and secret scan (gitleaks).
- [x] Super Admin auth and tenant scope implemented and tested before any client data.
- [x] Audit ledger and approval primitives exist and are enforced inside the Tool Gateway.
- [x] Zero-cost guard blocks paid/unverified providers (tested); no provider adapter is enabled.
- [x] Service taxonomy imported (19 families / 76 subcategories / 224 services), truthful readiness defaults.
- [ ] First vertical slice chosen: one web application project from intake to staging UAT (requires a Docker-host staging runner).
