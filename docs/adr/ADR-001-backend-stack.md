# ADR-001: Single Backend Stack

**Decision:** FastAPI + SQLAlchemy 2.x + Alembic + PostgreSQL + Pydantic v2.

**Context:** The preserved v5.3 baseline specifies FastAPI, SQLAlchemy and Alembic. The system needs async APIs, webhooks, OpenAPI, typed schemas and a single maintainable backend for a solo developer.

**Consequences:** Do not introduce Django as a second backend for this product. Django may be used in unrelated client projects. Use modular routers/services/repositories in this application. Frontend is HTML + HTMX + Alpine.js initially. Reconsider only with measured need and a new ADR.
