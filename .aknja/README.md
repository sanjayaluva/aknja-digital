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

## Development round protocol

Every development request ("continue developing...") is one **round** and must
update ALL of the following before it is considered done — code alone is an
incomplete round:

1. **Code + tests** — the increment itself; suite and `ruff` green; evidence
   (test names, command output) recorded for step 5.
2. **`tasks/TASK_LOG.md`** — append a task record following the Task Record
   Contract (`tasks/README.md`): goal, capability, acceptance criteria,
   verification evidence, status. A round is `COMPLETED` only when its
   acceptance criteria are independently verified.
3. **`memory/`** — append a reviewed, non-sensitive episodic summary of what
   was built/decided, with provenance (commit, tests, docs). No secrets, no
   client data.
4. **`docs/`** — update every numbered doc the round touches (backlog
   `docs/32`, roadmap `docs/04`, runbook `docs/41`, provider register
   `docs/33`/`34` when providers change, SRS erratum when a doc-sourced
   assumption is invalidated — like the HF Spaces withdrawal).
5. **`STATUS.md`** — update the evidence table: new rows for new subsystems,
   corrected test counts, and the "Not claimed" list must stay truthful.
6. **Commit + push** — one commit per round with a message that says what
   changed and why; the commit hash goes into the task record and memory entry.

A round that changes docs only (no code) still updates 2–6. Rounds never
mark anything `COMPLETED` on intention — only on recorded evidence.
