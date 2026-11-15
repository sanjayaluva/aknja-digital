# Source of Truth & Memory

- Git: canonical versioned requirements, ADRs, policies, prompts, schemas, code, tests and runbooks.
- PostgreSQL: live business/runtime state, approvals, task runs, provider usage, audit events.
- Object storage: deliverables, release artifacts, encrypted backup artifacts.
- Vector index: derived retrieval index only; rebuildable from authorized canonical sources.
- Secrets manager/environment: credentials only; never Git or prompts.

Every AI run records repository commit SHA, policy version, project/environment scope, input references, tool calls, outputs and verification evidence. Memory records include provenance, timestamp, scope, sensitivity, retention, source IDs and approval status.

Conflict precedence: Super Admin override → protected governance policy → approved current repository requirements/ADR → live operational DB state → approved memory → unverified agent/external content. Surface conflicts; do not guess.
