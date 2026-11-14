# Development Start Checklist

- [ ] Private repository exists and branch protection is enabled.
- [ ] `.aknja/` structure committed.
- [ ] FastAPI stack decision accepted and dependency versions pinned.
- [ ] `.env.example` reviewed; real secrets stored outside Git.
- [ ] Docker Compose local DB starts.
- [ ] Alembic initial migration runs.
- [ ] `/health/live` and `/health/ready` work.
- [ ] CI runs lint, type checks, tests and secret scan.
- [ ] Super Admin auth and tenant scope are implemented before client data.
- [ ] Audit and approval primitives exist before AI tool execution.
- [ ] Zero-cost guard blocks paid actions before provider adapters are enabled.
- [ ] Service taxonomy imported with readiness `PLANNED` by default.
- [ ] First vertical slice chosen: one web application project from intake to staging UAT.
