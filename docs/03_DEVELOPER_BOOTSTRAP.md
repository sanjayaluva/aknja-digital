# Developer Bootstrap

## Prerequisites
- Git, Python 3.12+, Docker Engine/Desktop with Compose plugin.
- PostgreSQL 16+ locally or via Compose.
- Node.js LTS only for frontend asset tooling if needed.
- Playwright browser dependencies for E2E tests.
- Access to private `aknja-digital` repository.
- No external provider keys required for core local startup.

## Initial repository structure
```text
aknja-digital/
  .aknja/
  app/
    main.py
    core/
    modules/
    api/
    templates/
    static/
  database/
  tests/
  infra/
  docs/
  alembic/
  pyproject.toml
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
6. Start API with `uvicorn app.main:app --reload`.
7. Check `/health/live` and `/health/ready`.
8. Run `pytest`, Ruff, type checks and API tests.
9. Install Playwright browsers and run E2E suite.
10. Never use production secrets or production data locally.

## First implementation milestone
A clean checkout must run locally with no AI provider key and no external paid service. Core admin, health, service catalog and project tracking must work without AI.
