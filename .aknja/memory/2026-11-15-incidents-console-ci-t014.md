# Episodic memory — Admin incidents console + first green CI (T-014, 2026-11-15)

**Scope:** EPISODIC · **Sensitivity:** INTERNAL · **Approved:** yes (founder-reviewed)

## What was built

**Admin incidents console** (operator surface for T-013): `/admin/incidents`
list (status filter chips, active count alert, severity/status tags, links),
`/admin/incidents/{id}` detail (description, recovery-actions table, timeline
newest-first with AI_DIAGNOSIS rendered as preformatted text), and a
CSRF-protected **manual close** that writes a CLOSED_BY_OPERATOR timeline
entry and an `incident.closed` audit event. Closing only stops tracking —
the monitor's dedupe spans OPEN/INVESTIGATING/MITIGATED, so the next failure
opens a fresh incident (tested). Cross-tenant detail/close 404s (tested).
New visual baseline `admin-incidents` (empty state — reseed wipes incidents;
no date text, stable); all 9 baselines re-synced byte-exact in one run.

**CI stabilization — first fully green pipeline.** The push of T-011..T-013
gave the first real runs of the new workflow; diagnosis from job logs:
- 9a82b3a: test SUCCESS (the dependency-manifest fix is proven on a clean
  runner — this was the original latent-red bug), security failed at
  "Set up job": the gitleaks-action pin `ff98106e4c1b2...` was an
  unresolvable SHA — the security job had NEVER run since T-003. Real v2
  tag commit: `ff98106e4c7b2bc287b24eaf42907196329070c7`.
- e2e failed in the scratch-DB step: the AKNJA_E2E_DATABASE_URL is a
  SQLAlchemy scheme (`postgresql+psycopg://`) — raw psycopg rejects it;
  strip the dialect suffix before connecting.
- bd723b9: test + security green; e2e 10/11 — only the FIRST login test
  timed out (>10s `wait_for_url`): cold-start on a 2-core runner (Jinja
  compile, pool init, first argon2 verify). Fixed with a server-fixture
  warm-up (GET /login + /healthz/ready) and a 30s login timeout.

## Verification

Local: 179/179 (7 new UI tests, 20/20 e2e layer), ruff clean. CI (GitHub):
test SUCCESS, security SUCCESS (first in repo history), e2e one cold-start
failure with the fix queued in this commit.

## Lessons

- Job-level "Set up job" failure = unresolvable action pin, not a runtime
  bug — check `actions/<job>/logs` before touching job steps.
- SQLAlchemy URLs must never be handed to raw psycopg: `+psycopg` is a
  dialect marker, not a scheme.
- CI runners are ~2-core: first-request budgets need warm-ups or generous
  timeouts; later identical tests passing is the cold-start signature.
