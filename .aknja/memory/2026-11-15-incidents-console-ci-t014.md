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

## Addendum — first all-green pipeline (c84bf15, run 43694546044)

The e2e CI loop took three iterations to close:
1. bd723b9 fixed gitleaks + psycopg scheme → test + security green, e2e
   10/11 (first-login cold start >10s on the 2-core runner).
2. 8f7d14f added warm-up + 30s + login retry → the retry INTRODUCED a
   failure: when attempt-1's login XHR completed late, its Set-Cookie made
   attempt-2's goto('/login') redirect to /admin (authenticated users are
   302'd away from /login), and page.fill timed out on the admin page.
3. c84bf15 hardened login() with an already-logged-in guard before every
   attempt ('/login' not in page.url after goto = success), up to 3
   attempts, real auth errors (#login-error visible) never retried.

Result: test + e2e + security ALL GREEN — first fully green pipeline in
repo history. The runner stall itself (one request >30s, self-healing,
never reproducible locally — 88/88 logins across 8 local runs) remains an
environment property; the harness now tolerates it and dumps page content
if it ever exhausts retries.
