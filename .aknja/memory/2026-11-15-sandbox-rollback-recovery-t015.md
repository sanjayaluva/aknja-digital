# Episodic memory — sandbox rollback recovery + lint parity (T-015, 2026-11-15)

**Scope:** EPISODIC · **Sensitivity:** INTERNAL · **Approved:** yes (founder-reviewed)

## What happened

Between messages the sandbox was rolled back to an early snapshot: the
aknja-digital clone, the venv, the Playwright browsers and the PAT file
were all gone. Nothing of value was lost — every task had been committed
and pushed at the moment it finished (rule: never leave work unpushed),
so GitHub was the single source of truth at a622704.

Recovery used the T-002 tooling itself (`scripts/restore_and_audit.sh
public` with EXPECT_COMMIT/EXPECT_TESTS overrides): clone → uv sync
--frozen → health check → audit. Two artifacts needed re-setup by hand:
the PAT file (600, outside any repo) and the repo-local credential helper
for pushes; `playwright install chromium` for the 20 e2e tests.

## What the health check surfaced

`ruff check .` reported 37 findings while CI was green — CI linted
`app tests` only, and alembic/ + infra/ had drifted (I001, UP007/UP035,
F401, plus an unjustified blind-except noqa and an implicit-concat style
issue). Fixed all 37 (34 auto, 3 by hand), migration files touched for
typing/import style only, re-verified with the full suite (179/179 — the
e2e fixture exercises alembic upgrade head) and tightened the CI lint
step to `ruff check .` so the gap cannot reopen.

Also re-confirmed the authoritative audit tool (infra/) reports
81 installed / 0 CVE / 0 unused / 0 undeclared / 0 unresolved; the OLD
workspace copy of the tool (pre-T-011) that the rollback restored
over-reports (4 "unused" that are real dependencies) — always run the
repo's version.

## Lessons

- The sandbox CAN roll back between messages: push every task
  immediately; keep recovery scripts in the workspace (they survived).
- A green CI proves only what CI runs — a lint scope of `app tests`
  hid drift in alembic/ and infra/. Lint the whole repo.
