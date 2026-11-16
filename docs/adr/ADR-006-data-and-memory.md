# ADR-006: Data and Memory Sources of Truth

**Decision:** Git for versioned artifacts; PostgreSQL for live state; object storage for binary artifacts; vector index as derived/rebuildable. No secrets/client data in Git. AI run context is scoped and provenance-aware.
