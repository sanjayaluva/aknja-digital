# Episodic memory — CI hardening: lockfile, e2e job, portability (T-012, 2026-11-15)

**Scope:** EPISODIC · **Sensitivity:** INTERNAL · **Approved:** yes (founder-reviewed)

## What was built

Closed the CI/production-readiness infrastructure gap surfaced by the T-011
audit follow-ups:

1. **uv.lock committed** (83 packages). CI installs via
   `uv sync --frozen --all-extras` — installs are bit-reproducible from the
   lockfile instead of re-resolving ranges on every runner. The runbook
   bootstrap now leads with uv (pip fallback documented).
2. **CI e2e job** (new): postgres service container + cached chromium +
   `AKNJA_E2E_DATABASE_URL`. The 11 functional Playwright flows now run in CI,
   not only in the sandbox. The unit job runs `-m "not e2e"` for fast feedback.
3. **Conftest portability**: `PGDATA` dirs and the alembic subprocess `cwd`
   were hardcoded to `/home/z/my-project/...` — e2e was unrunnable on any
   other machine. Now derived from the repo root; pgdata clusters live inside
   the repo (gitignored `pgdata*/`). e2e honors `AKNJA_E2E_DATABASE_URL`
   (external DB, no pgserver cluster) — the exact contract CI uses.
4. **Visual baseline protocol**: `infra/baseline_verify.py` decides
   drift-vs-regression from canvas size, edge-map diff and changed-row band
   heights (text bands 8–15px; layout bands >100px). docs/41 documents the
   regeneration procedure.

## Decisions worth remembering

- **Visual baselines stay out of CI.** They are tied to the font stack of the
  generating machine; ubuntu-runner fonts would fail the 0.2% tolerance
  spuriously. Functional e2e is portable; pixel comparison is not.
- **The admin-providers drift root cause** (T-011) was finally pinned down:
  the page renders NO dates (seed timestamps are frozen at a constant); the
  37 text-band diff came from the chromium build change (1200→1255) affecting
  table-font rasterization. Two consecutive runs in the same environment are
  pixel-identical, so baselines are stable until the rendering stack changes.
- **pgserver servers die with their process.** A simulation that creates a
  scratch DB in one process and runs pytest in another loses the unix socket.
  CI avoids this by design: the service container outlives every step.

## Verification

`uv sync --frozen --all-extras` + pytest 160/160 in the locked state · CI e2e
path simulated locally against an external scratch DB with a live server:
11/11 flows pass · two consecutive visual runs pixel-identical ·
`baseline_verify.py` reproduces the T-011 analysis (drift-only, exit 0) ·
ruff clean.

## Push status

T-011 (2f92067) and T-012 commits are local pending GitHub credentials —
the owner-set public clone allows read, but push needs the PAT re-supplied
into the sandbox.
