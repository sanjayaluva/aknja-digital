# ADR-007: Synchronous SQLAlchemy 2.x endpoints

**Status:** Accepted (14 November 2026)

## Context
The v5.2 legacy baseline mentioned an "async backend". v6.1 §8 mandates FastAPI + SQLAlchemy 2.x without prescribing driver concurrency. The platform's workload profile is a solo-founder operations console with low concurrency (SRS §8: "database-backed durable job table initially; low concurrency").

## Decision
Use **synchronous SQLAlchemy 2.0** with psycopg 3 and `def` endpoints (FastAPI runs them in a threadpool). The quota engine relies on `SELECT … FOR UPDATE` row-locking, which is straightforward and battle-tested in the sync driver.

## Consequences
- Simpler, fully typed service layer; no async session leakage pitfalls.
- Threadpool concurrency is sufficient for the admin console + portal load profile.
- If measured load later requires it, migrate hot paths to `postgresql+psycopg_async` behind the same service interfaces; revisit with a new ADR.
