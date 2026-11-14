# .aknja — AI & Development Workspace

Read order:
1. `SYSTEM.md` — authority, invariants and operating model.
2. `STATUS.md` — evidence-based implementation state.
3. `architecture/` — architecture decisions and trust boundaries.
4. `agents/` — capability templates, not permanent privileged employees.
5. `policies/` — protected governance policy.
6. `workflows/` — state machines and execution contracts.
7. `memory/` — reviewed, non-sensitive summaries only.
8. `tasks/` and `decisions/` — implementation tracking and ADRs.

Git is canonical for versioned requirements, policy, architecture, prompts, code, schemas, tests and runbooks. PostgreSQL is canonical for live project/task/approval/job/audit state. Vector indexes are derived and rebuildable. Object storage holds artifacts. Secrets and client production data do not belong here.

Do not put volatile runtime state, raw logs, caches, credentials, client uploads or database dumps in this directory.
