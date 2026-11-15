# Developer Bootstrap

## Prerequisites
- Git, Python 3.12+, Docker Engine/Desktop with Compose plugin.
- PostgreSQL 16+ locally or via Compose.
- Node.js LTS only for frontend asset tooling if needed.
- Playwright browser dependencies for E2E tests.
- Access to private `aknja-digital` repository.
- No external provider keys required for core local startup.

## Initial repository structure (implemented)
```text
aknja-digital/
  .aknja/            # governance, policies, state machines, status evidence
  app/
    main.py          # FastAPI factory, middleware, health, router wiring
    core/            # config, db, security, logging, errors, enums
    modules/         # identity, governance, crm, catalog, commercial,
                     # delivery, ai, resources, hosting, ops
    api/             # deps (auth/CSRF/RBAC) + api/v1 routers
    ui/              # server-rendered admin + portal routes
    templates/       # Jinja2 (base, admin/*, portal/*, auth/*)
    static/          # vendored htmx/alpine + design system CSS
  alembic/           # authoritative migrations
  tests/             # pytest suite (real PostgreSQL)
  infra/             # deployment templates and scripts
  docs/              # specifications, ADRs, runbooks
  pyproject.toml     # pinned dependencies
  alembic.ini
  Dockerfile
  compose.yaml
  .env.example
```

## Bootstrap sequence
1. Clone the private repository.
2. Copy `.env.example` to `.env`; generate a unique `SECRET_KEY`.
3. Start PostgreSQL using `docker compose up -d db`.
4. Create virtual environment and install pinned dependencies.
5. Run `alembic upgrade head`.
6. Bootstrap platform data: `python -m app.cli create-super-admin`, `python -m app.cli seed`, `python -m app.cli import-taxonomy`, then `python -m app.cli verify-install` (all checks must PASS).
7. Start API with `uvicorn app.main:app --reload`.
8. Check `/health/live` and `/health/ready`.
9. Run `pytest`, Ruff, type checks and API tests.
10. Never use production secrets or production data locally.

The full verified sequence with expected output lives in
`docs/41_LOCAL_DEVELOPMENT_AND_TEST_RUNBOOK.md`.

## First implementation milestone
A clean checkout must run locally with no AI provider key and no external paid service. Core admin, health, service catalog and project tracking must work without AI.
