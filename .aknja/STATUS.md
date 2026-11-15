# Implementation Status — Core Platform Implemented (v0.1.0)

**Last updated:** 14 November 2026 · see `docs/41_LOCAL_DEVELOPMENT_AND_TEST_RUNBOOK.md` for reproduction steps.

Evidence rule (unchanged): a status changes only with tests, commands and their output — never intention or a container start.

| Area | Status | Evidence |
|---|---|---|
| Requirements and architecture | SPECIFIED | Approved ADRs 001–007; traceability review pending |
| FastAPI application | IMPLEMENTED | `app/` modular monolith; 102 routes; `/health/live`, `/health/ready` verified against PostgreSQL; `tests/` suite |
| Authentication/RBAC/tenant isolation | IMPLEMENTED + TESTED | `tests/test_auth_rbac.py` — login/lockout/CSRF, deny-by-default RBAC, cross-tenant 404s, portal scoping (14 tests) |
| Central AI Orchestrator | IMPLEMENTED + TESTED | `app/modules/ai/orchestrator.py` state machine; `tests/test_tool_gateway.py` — illegal transitions, no COMPLETED without verification evidence, emergency stop; LLM steps (`execute_llm_step`) — `tests/test_orchestrator_llm.py` (6): state gating, BLOCKED/RETRY_WAIT outcome parking, CONFIDENTIAL pre-egress block |
| Telegram notification outbox | IMPLEMENTED + TESTED (live bot pending token) | `app/modules/ops/notifications.py` + `notification_outbox` (migration `c7d2e8f4a9b1`, roundtrip-verified): idempotent durable enqueue, provider-confirmed delivery (200+ok), 429 retry_after backoff, terminal FAILED on definitive rejection, unconfigured channel loses nothing; hooks: approval requested, quota hard-stop, AI run parked; `tests/test_notifications.py` (13); CLI `process-notifications` / `send-test-notification` |
| LLM quality benchmark + §6 gate | IMPLEMENTED + TESTED (real-egress evidence run) | `app/modules/ai/benchmark.py`: v1 bank, 36 scenarios (7 tasks × ml/en/hi/ta), deterministic evaluators (JSON/label/entity/script/facts/length/sections), floors (classification+translation 1.0, generative 0.75), `provider_quality_benchmarks` rows (migration `d8e3f6a7c2b4`, roundtrip-verified), gate in `llm_complete` (fresh failed benchmark blocks failed tasks only), founder alert on failure, CLI `run-llm-benchmark`; `tests/test_benchmark.py` (16) |
| LLM inference layer | IMPLEMENTED + TESTED (adapters mocked) | `app/modules/ai/inference.py`: 7 task profiles, adapters for groq/github_models/gemini/workers_ai, per-attempt quota admission, audited 429/5xx failover, fail-closed PENDING_MANUAL; `tests/test_ai_inference.py` (8); `llm_call_logs` stores prompt hash only; governed `llm.generate` tool; `llm-ping` CLI demonstrated (unverified → fail-closed; verified → real HTTP round trip) |
| Tool Gateway | IMPLEMENTED + TESTED | `tests/test_tool_gateway.py` — allow-list, schema, RESTRICTED data block, approval-hash binding, no self-approval, idempotent replay, tenant scope |
| Service Catalog | IMPLEMENTED + TESTED | Full source taxonomy preserved: 19 families, 76 subcategories, 224 leaf services; truthful availability/readiness; `tests/test_lifecycles.py` |
| Resource/Quota Orchestrator | IMPLEMENTED + TESTED | `tests/test_quota.py` — ZERO_COST_ONLY rejects paid/unverified; stale/unknown quota fails closed; 95% hard-stop; concurrent reservations cannot oversubscribe (row-lock); circuit breaker; free-pool failover |
| Commercial lifecycle | IMPLEMENTED + TESTED | `tests/test_lifecycles.py` — lead→client→proposal→contract→scope freeze→30/30/40 invoices→manual payment reconciliation→PAID |
| Project delivery + gates | IMPLEMENTED + TESTED | STAGING_UAT requires active preview; PRODUCTION_HANDOFF requires accepted UAT; tasks require REVIEW→VERIFIED→DONE |
| Zero-hardcode system settings | IMPLEMENTED + TESTED | 43 seeded settings (SRS §8.2 Tabs 1–7); typed validation; audit on save; protected keys not runtime-editable |
| Audit ledger | IMPLEMENTED + TESTED | Hash-chained, content-recomputing verification; DB-level append-only trigger (UPDATE/DELETE raise); tamper detection test |
| Admin UI + client portal | IMPLEMENTED | 12 admin screens + portal (projects, milestones, staging previews, feedback, UAT, invoices); server-rendered HTMX/Alpine; `tests/test_ui.py` (18 tests) |
| Project workspace/staging | PARTIAL | Preview-link lifecycle, evidence and cleanup models implemented; Compose-based staging provisioning requires a Docker host (design in docs/15) |
| Production hosting | SPECIFIED, OPTIONAL | Not deployed. Requires capacity admission, backup/restore drills and contract per docs/19, docs/38 |
| QA/visual verification | DONE | 153 tests passing in one command (unit/integration/contract + 11 Playwright E2E flows + 8 visual baselines with 0.2% pixel-diff tolerance) against real PostgreSQL 16; E2E layer found and fixed six ship-blocking UI bugs (login form serialization, 422→500 handler crash, principal/CSRF wiring, audit NULL-tenant visibility, logout redirect, unstable row ordering) |
| Client portal UAT workflow | IMPLEMENTED + TESTED | Portal tests in `tests/test_ui.py`, `tests/test_auth_rbac.py` |
| Production incident automation | SPECIFIED | Incident/support/backup models + UI-ready; automation deferred (docs/20) |

**Test suite:** 153 tests, all passing (`pytest -q`), including concurrency tests against real PostgreSQL, 11 real-browser Playwright E2E flows and 8 visual-baseline comparisons (skips cleanly without Chromium; `AKNJA_E2E=skip` to disable). Lint: `ruff check app tests` clean.

**Hosting plan change (2026-11-14):** Hugging Face Spaces Docker/Gradio hosting moved to paid plans; withdrawn from the free pool (SRS §2.1 erratum, docs/34). Free staging rebases onto OCI Always-Free ARM; Hugging Face remains only as a serverless inference candidate.

**Not claimed:** live provider accounts verified in the actual console — the candidate pool (32 providers across 9 categories — doc-sourced pool plus the doc 34 web-researched watchlist: Workers AI, GitHub Models, UptimeRobot, Better Stack, Brave, Tavily, Redis Cloud) is seeded as FREE_UNVERIFIED/disabled via `register-provider-candidates`, and activation requires the audited `verify-provider` step (docs/33 worksheet; implemented and tested in `tests/test_provider_candidates.py`). Staging/production deployment, LLM adapters exercised against live accounts (HTTP adapters are implemented and mocked-tested; every external provider stays disabled until the audited `verify-provider` step per SRS §14), live Telegram bot (outbox implemented + tested end-to-end with mocks; delivery requires the founder to set TELEGRAM_BOT_TOKEN/TELEGRAM_ADMIN_CHAT_ID via @BotFather), a benchmark run against a REAL provider account (the runner itself is done and evidence-tested via real egress; live floors need verified credentials).
