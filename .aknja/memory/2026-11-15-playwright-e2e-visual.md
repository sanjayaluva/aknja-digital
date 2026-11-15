# Episodic memory — Playwright E2E + visual verification (2026-11-15)

**Scope:** EPISODIC · **Sensitivity:** INTERNAL · **Approved:** yes (founder-reviewed)

## What was built

Real-browser E2E layer (docs/16) for the admin console and client portal:
`tests/e2e/` harness boots the actual FastAPI app via uvicorn on a free
localhost port against a dedicated scratch database (`pgdata-aknja-e2e`
→ `aknja_e2e`, alembic-migrated, audit trigger installed, deterministically
seeded: founder + CLIENT_OWNER users, lead, client, project+task, approval,
catalog taxonomy, 32-provider candidate pool; created/updated timestamps
frozen at a fixed instant for reproducible screenshots). 11 functional
tests drive login/lead qualification (NEW→CONTACTED→QUALIFIED), task
delivery, approval decisions, portal feedback, RBAC (client gets 403 on
/admin, anonymous redirected), audit visibility. 8 visual tests compare
full-page screenshots against committed baselines in
`tests/e2e/baselines/` at 1280×800 (login also at 390×844 mobile) with a
0.2% pixel-diff tolerance; dynamic screens (audit ledger, live
timestamps) are excluded by policy. `AKNJA_E2E_UPDATE_BASELINES=1`
regenerates baselines; `AKNJA_E2E=skip` skips the layer where Chromium
is unavailable. Reseeding uses TRUNCATE (never DROP) so the running
server's pooled connections stay valid.

## Bugs the browser layer caught (all fixed this round)

- `/api/v1/auth/login` was JSON-only, but the htmx form posts
  urlencoded — **every real-browser login 422'd**. TestClient tests
  posted JSON directly and never noticed. Fix: dependency accepting both
  content types.
- The RequestValidationError handler fed pydantic error dicts containing
  raw bytes to json.dumps → **422 turned into 500**. Fix: sanitize before
  serializing.
- `request.state.principal` was never set by server-rendered routes →
  every admin/portal page rendered the anonymous shell (no sidebar/nav)
  **and empty CSRF hidden inputs, so every form POST 403'd**. Fix: publish
  the principal in `current_principal()`.
- The audit console filtered `tenant_id == principal.tenant_id`, hiding
  all NULL-tenant system events — **auth.login never appeared anywhere**.
  Fix: include `tenant_id IS NULL`.
- Logout returned JSON with no redirect instruction — the browser stayed
  on the stale console. Fix: `HX-Redirect: /login`.
- Providers page + catalog relationship loads had no total ordering —
  row order varied between runs (1.5% pixel diff on identical data).
  Fix: ORDER BY with unique tiebreakers (`provider`; `sort_order, code`;
  `sort_order, name`).

## Lessons worth remembering

- TestClient-with-injected-cookie bypasses exactly what a browser
  exercises: form serialization, htmx request/response contracts, and
  template-rendered CSRF tokens. An E2E layer is not redundant with
  route smoke tests — this round it found six ship-blocking bugs the
  132-test suite had green-lit for weeks.
- Postgres heap order is not a stable sort. Any list page or ORM
  relationship without a TOTAL order (unique tiebreaker included) will
  eventually shuffle under churn; visual baselines turn that into a
  caught failure instead of a silent UI change.
- Frozen seed timestamps (UPDATE after seeding; audit table excluded —
  append-only trigger) make full-page screenshots byte-stable across
  days; TRUNCATE-and-reseed on the live DB keeps the uvicorn pool valid.
- `get_settings` is lru-cached process-wide: any fixture that repoints
  DATABASE_URL must `cache_clear()` (and reset the engine), or later
  fixtures silently bind to the wrong database. Both conftests now do
  this defensively.

**Provenance:** this round's commit; `tests/e2e/` (11 + 8 tests),
`tests/test_ui.py` (+2 regression), `tests/e2e/baselines/*.png` (8);
153 tests passing, ruff clean; full suite stable across repeated runs.
