# Task Log — implementation rounds

Records follow the Task Record Contract (`tasks/README.md`). Platform-internal
tasks: `project_id`/`tenant_id` are `—` (internal engineering, not a client
engagement). Status is `COMPLETED` only with recorded verification evidence.

## T-001 — Core platform (foundation → delivery)

- task_id: T-001 · project_id/tenant_id: — · capability: software_engineer
- goal: FastAPI modular monolith, PostgreSQL schema + Alembic, auth/RBAC/tenant
  isolation, audit ledger, service catalog (19/76/224 taxonomy), commercial
  lifecycle, project delivery + gates, settings, admin UI + client portal.
- inputs: docs/01 SRS v6.1, source docs in `docs/source_*`
- data_classification: INTERNAL · dependencies: none
- acceptance_criteria: suite green on real PostgreSQL; cross-tenant denial;
  no COMPLETED without verification evidence; taxonomy fully preserved.
- allowed_tools: — · resource_constraints: zero-cost only
- quota_reservation: n/a · approval_requirement: none
- deadline: — · idempotency_key: commit cf3d22e
- status: COMPLETED
- artifacts: `app/` (11 modules, 102 routes), `alembic/`, `tests/`
- verification_evidence: 80 tests passing pre-T-004 (now 101 total);
  `tests/test_auth_rbac.py`, `test_lifecycles.py`, `test_ui.py`,
  `test_governance.py`, `test_quota.py`
- failure_reason: —

## T-002 — Zero-cost quota engine + provider registry (docs/13, docs/33)

- task_id: T-002 · capability: software_engineer
- goal: provider registry with verification workflow, usage ledger, quota
  snapshots, atomic row-locked reservations, 95% hard stop, circuit breaker,
  free-pool failover, zero-cost guard.
- acceptance_criteria: concurrent admissions cannot oversubscribe; paid or
  unverified providers never admitted; stale/unknown quota fails closed.
- deadline: — · idempotency_key: commit 2962cba (with T-003)
- status: COMPLETED
- artifacts: `app/modules/resources/`, `tests/test_quota.py`,
  `tests/test_provider_candidates.py`
- verification_evidence: quota + candidate tests; `register-provider-candidates`
  and `verify-provider` CLI demonstrated on a fresh dev DB (docs/41 §9)
- failure_reason: —

## T-003 — Candidate pool expansion (docs/34)

- task_id: T-003 · capability: research_docs
- goal: doc-sourced stragglers (Colab, Modal, CF Pages, Jina, HF inference)
  + web-researched watchlist (Workers AI, GitHub Models, UptimeRobot,
  Better Stack, Brave, Tavily, Redis Cloud) with research dates and URLs.
- acceptance_criteria: every entry carries provenance (docs or URL + date);
  seeded FREE_UNVERIFIED/disabled only.
- status: COMPLETED
- verification_evidence: `tests/test_provider_candidates.py`; doc 34 tables
- failure_reason: —

## T-004 — HF Spaces withdrawal + LLM inference layer (v5.3.2 §5C)

- task_id: T-004 · capability: software_engineer
- goal: remove HF Spaces Docker hosting as a free option (provider moved it
  to paid plans); build the provider-neutral LLM inference layer.
- inputs: user decision + huggingface.co/docs/hub/en/spaces-overview
- acceptance_criteria: HF inference-only in registry with SRS §2.1 erratum;
  7 task profiles; adapters for groq/github_models/gemini/cloudflare_workers_ai;
  audited 429/5xx failover; fail-closed PENDING_MANUAL; prompt hash only in
  `llm_call_logs`; governed `llm.generate` tool (PUBLIC/INTERNAL only);
  `llm-ping` CLI.
- status: COMPLETED
- deadline: — · idempotency_key: commit 005aee9
- artifacts: `app/modules/ai/inference.py`, migration `b3f1a9c2d4e5`,
  `tests/test_ai_inference.py` (8), runbook §10
- verification_evidence: 95 tests passing at commit; CLI demo: unverified →
  fail-closed guidance, verified → real HTTP round trip to api.groq.com;
  gateway `allowed_data_classes` enforcement gap found by tests and fixed
- failure_reason: —

## T-008 — LLM quality benchmark runner + §6 inference gate (this round)

- task_id: T-008 · capability: software_engineer
- goal: implement the v5.3.2 §5C/§6 quality-preservation loop for the free
  LLM pool — benchmark prompts with golden expectations for ml/en/hi/ta,
  deterministic scoring against per-task floors, durable benchmark
  records (§7) and an eligibility gate in the inference layer.
- inputs: docs/source_provider_pools_v5.3.2.md §5C/§6/§7, TASK_PROFILES
- data_classification: INTERNAL · dependencies: T-005 (inference), T-006 (alerts)
- acceptance_criteria: versioned 36-scenario bank covering all 7 task
  profiles in all 4 languages; deterministic evaluators (JSON/schema
  validity, label match, entity+script preservation, key facts, length
  bounds, sections); per-task floors (classification/translation 1.0,
  generative 0.75); one provider_quality_benchmarks row per run; a
  failed fresh benchmark blocks the provider for the failed tasks only
  (passed / stale >30d / unbenchmarked / uncovered task = eligible);
  founder alert on failure; CLI run-llm-benchmark with honest exit code.
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED
- artifacts: `app/modules/ai/benchmark.py` (bank + evaluators + runner +
  gate), `ProviderQualityBenchmark` model + migration `d8e3f6a7c2b4`
  (roundtrip-verified), gate hook in `inference.py`, `benchmark.failed`
  template, CLI `run-llm-benchmark`, `tests/test_benchmark.py` (16)
- verification_evidence: 132 tests passing, lint clean; CLI evidence run
  with real egress (groq, dummy token): HTTP 403 recorded per scenario,
  FAILED verdict, exit 1, durable row + Malayalam founder alert queued
- failure_reason: —

## T-006 — Telegram notification outbox (docs/39 reliability, this round)

- task_id: T-006 · capability: software_engineer
- goal: wire the founder Telegram channel as a durable admin-notification
  outbox with the docs/39 reliability semantics, plus CLI delivery.
- inputs: docs/39, config TELEGRAM_BOT_TOKEN/TELEGRAM_ADMIN_CHAT_ID
- data_classification: INTERNAL · dependencies: T-001 (settings/tenant)
- acceptance_criteria: idempotent enqueue (unique key); provider-confirmed
  delivery only on 200/ok; exponential backoff honoring 429 retry_after;
  terminal FAILED on definitive rejection (400/403) with no re-attempt;
  unconfigured channel leaves rows PENDING with attempts 0; duplicate
  marker (`· ref`) in every body; hooks for approval requested, quota
  hard-stop and AI run parked; concurrent hard-stop workers must not
  crash admissions (savepoint on the unique-index race).
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED
- artifacts: `app/modules/ops/notifications.py`, `NotificationOutbox`
  model + migration `c7d2e8f4a9b1` (roundtrip-verified by
  scripts/check_migration_notification.py), hooks in governance/resources/
  orchestrator, CLI `process-notifications` / `send-test-notification`,
  `tests/test_notifications.py` (13)
- verification_evidence: 114 tests passing, lint clean; migration upgrade/
  downgrade/upgrade roundtrip PASS; quota concurrency tests still green
  with the hard-stop hook active
- failure_reason: —

## T-005 — Orchestrator LLM integration + progress protocol (this round)

- task_id: T-005 · capability: software_engineer
- goal: (a) wire agent runs to the inference layer via `execute_llm_step`
  with state-machine-governed outcome parking; (b) establish the development
  round protocol (this file, README, memory, STATUS, docs updates every round).
- inputs: v5.3.2 §5C, docs/09, `.aknja/workflows/ai-execution-state-machine.md`
- acceptance_criteria: LLM steps only in PLAN/EXECUTE_LOW_RISK/EXECUTE_APPROVED;
  capability must allow `llm.generate`; CONFIDENTIAL runs blocked pre-egress;
  PENDING_MANUAL → BLOCKED (RETRY_WAIT from EXECUTE_APPROVED); FAILED →
  RETRY_WAIT; SUCCEEDED records event + audit and never completes the run.
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED
- artifacts: `app/modules/ai/orchestrator.py` (`execute_llm_step`,
  `CAPABILITY_TASKS`), `tests/test_orchestrator_llm.py` (6), this protocol
- verification_evidence: 101 tests passing, lint clean; tests pin every
  acceptance criterion above
- failure_reason: —

## T-007 — Playwright E2E + visual comparison (this round)

- task_id: T-007 · capability: software_engineer
- goal: real-browser E2E for critical admin/client workflows and
  screenshot-vs-baseline visual comparison per docs/16.
- inputs: docs/16, docs/32 Epic G, SRS §14
- acceptance_criteria: critical workflows (auth, lead→qualify, task
  delivery, approval decision, portal feedback, RBAC boundaries, audit
  visibility) pass in Chromium against the real app; visual diff at
  agreed breakpoints (1280×800; login 390×844) against committed
  baselines with explicit tolerance and documented dynamic-content
  exclusions; layer skips cleanly without Chromium; existing suite
  unaffected.
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED
- artifacts: `tests/e2e/` (harness + 11 functional + 8 visual tests),
  `tests/e2e/baselines/*.png` (8), regression tests in
  `tests/test_ui.py` (+2); product fixes found by E2E:
  login urlencoded-form support, validation-error sanitizer,
  `request.state.principal` wiring (sidebar + CSRF tokens),
  audit NULL-tenant visibility, logout `HX-Redirect`, stable ordering
  (providers page, catalog relationships)
- verification_evidence: 153 tests passing (twice, stable), ruff clean;
  visual compare mode deterministic across fresh runs (0.0000% diff);
  comparator sensitivity verified (synthetic 5.86% change caught)
- failure_reason: —

## T-010 — Backup/restore + maintenance mode (this round)

- task_id: T-010 · capability: software_engineer
- goal: implement the v5.3.2 §5A required-architecture items "Database
  backup and tested restore" and "Write freeze / maintenance mode during a
  controlled promotion" (backlog H5), per docs/22 semantics.
- inputs: v5.3.2 §5A, v5.3.1 L141 (quota exhaustion -> read-only mode),
  docs/22, docs/32 Epic H
- acceptance_criteria: pg_dump artifacts with checksummed manifests; restore
  drill to an ISOLATED scratch DB verifying counts/schema/audit chain and
  recording duration; pruning never removes the last verified backup;
  unverified backups are refused for drills; write freeze returns 503 +
  Retry-After for mutating requests while reads, /healthz and auth stay up;
  activation/deactivation audited + founder-notified once per transition;
  everything CLI-driven and testable in-sandbox with bundled pg tooling.
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED
- artifacts: `app/modules/ops/backup.py` (create/verify/drill/prune),
  `app/modules/ops/maintenance.py` (set/is/ TTL read + middleware),
  maintenance middleware in `app/main.py`, CLI `backup
  create|verify|drill|prune` + `maintenance on|off|status`, new settings
  (ops_recovery tab), 5 notification templates, `tests/test_backup_recovery.py`
  (7), docs/22 restore sequence
- verification_evidence: 160 tests passing, ruff clean; live CLI smoke on a
  real cluster: create (72ms, 88 rows/58 tables) -> verify OK (freshness
  0.0h) -> drill PASSED (counts/schema/audit_chain ok, scratch DB dropped)
  -> tampered artifact -> verify FAIL + drill refuses + prune refuses
  ("no verified backup would remain") -> maintenance on/status/off cycle
- failure_reason: —

## T-011 — Dependency audit + manifest/CIF fixes (this round)

- goal: restore the workspace after a sandbox recycle and audit dependencies
  (original task-list item); deliver a dependency-integrity state where a clean
  `pip install -e ".[dev]"` boots the app, the suite is green on a fresh
  environment, and the audit reports zero findings.
- inputs: recovery report 2026-11-15 (sandbox recycle, private remote, no local
  copy), repo @ 455054e re-cloned after the owner set it public, audit tooling
  developed and fixture-tested during the blocked period
  (`infra/dependency_audit.py`), docs/33 zero-cost invariant, docs/41 runbook
- acceptance_criteria: fresh-venv editable install succeeds; app boots; pytest
  160/160 incl. e2e; ruff clean; audit inventory with direct/transitive +
  license classification; CVE scan via pip-audit same-environment; findings
  either resolved or documented with follow-ups.
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED
- artifacts: `infra/dependency_audit.py` (inventory/import cross-check/pip-audit
  CVE scan, same-env invariant, PEP 503 normalization, lazy-import allowlist),
  `docs/42_DEPENDENCY_AUDIT.md` (findings + resolutions + follow-ups),
  pyproject.toml (explicit package discovery; +argon2-cffi/jinja2/
  email-validator/python-multipart runtime; +pgserver/playwright/Pillow/
  pip-audit dev; pytest>=9.0.3; Pillow>=13), ci.yml (AKNJA_TEST_DATABASE_URL),
  regenerated `tests/e2e/baselines/admin-providers.png`
- verification_evidence: clean venv `pip install -e ".[dev]"` + app import OK;
  ruff clean; pytest 160 passed (Pillow 13, chromium 159, regenerated baseline);
  audit final: 81 installed / 0 CVE / 0 unused / 0 undeclared / 0 unresolved,
  exit 0; fixed-in-audit-bugs: pip-audit JSON schema (vulns field), cross-venv
  pip-audit resolution, name normalization, CVE dedup; baseline drift verified
  structural (37 text-line bands 8–13px, canvas identical 1280×3152)
- failure_reason: —

## T-012 — CI hardening: uv lockfile, e2e job, portability (this round)

- goal: make CI exercise the full system the way the sandbox does — locked
  reproducible installs, real-browser E2E in CI, and tests free of
  machine-specific assumptions (closes the docs/42 follow-ups 2+3 and Phase 5
  leftovers; visual-baseline protocol documented and tool-supported).
- inputs: docs/42 follow-ups, docs/16 (visual semantics), docs/41 runbook,
  T-011 audit state, ci.yml, tests/conftest.py + tests/e2e/conftest.py
- acceptance_criteria: uv.lock committed and CI installs via
  `uv sync --frozen --all-extras`; a dedicated CI e2e job runs the 11
  functional Playwright flows against the postgres service container;
  conftest paths derived from the repo root (no /home/z hardcodes); e2e
  honors AKNJA_E2E_DATABASE_URL; baseline regeneration protocol exists as a
  committed tool with a drift-vs-regression verdict.
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED
- artifacts: uv.lock (83 packages), rewritten ci.yml (test job on uv +
  `-m "not e2e"`, new e2e job with chromium + browser cache +
  AKNJA_E2E_DATABASE_URL, security job unchanged), conftest portability fixes
  (repo-relative pgdata dirs, _REPO_ROOT cwd, e2e external-DB override),
  `infra/baseline_verify.py` (canvas/edge/band analysis, verdict + exit code),
  docs/41 bootstrap/test/e2e/visual sections rewritten
- verification_evidence: `uv sync --frozen --all-extras` + full suite 160/160
  green in locked state (pytest-cov locked to 7.1.0); CI e2e code path proven
  locally by simulation — external scratch DB via AKNJA_E2E_DATABASE_URL with
  a live server: 11/11 functional flows pass; visual stability proven by two
  consecutive pixel-identical runs; baseline_verify.py reproduces the T-011
  admin-providers analysis (37 text-height bands, verdict drift-only, exit 0);
  ruff clean
- failure_reason: —

## T-013 — Incident automation: monitor, safe recovery, AI diagnosis (this round)

- goal: implement the Phase 8 automation slice of docs/20 — injected failure
  detected; safe recovery verified; unsafe action blocked (roadmap exit
  criteria) — on the existing Incident/outbox/backup building blocks.
- inputs: docs/20, roadmap Phase 8, Incident/Job/NotificationOutbox/
  BackupRecord models, T-006 outbox, T-010 backup freshness SLO, inference
  layer (governed fail-closed pool)
- acceptance_criteria: checks (backup freshness SLO, notification/job queue
  age, DB blocking locks) manage deduped incidents with timeline, severity
  escalation and founder notification on open/resolve; recovery is an
  EXHAUSTIVE allow-list of idempotent requeue actions with a rolling-hour
  circuit breaker; unknown/unsafe actions raise; AI diagnosis redacts
  secrets and fails closed without a verified provider; CLI-driven.
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED
- artifacts: `app/modules/ops/monitor.py` (4 checks, lifecycle, allow-list,
  breaker, redact + diagnose), 2 notification templates (incident.opened/
  resolved), 3 seeded settings (ops_recovery tab), CLI `monitor run` /
  `monitor diagnose`, `tests/test_monitor.py` (11)
- verification_evidence: 171/171 tests (11 new), ruff clean, audit
  81/0/0/0/0; live CLI smoke on a real cluster (scratch DB, migrated,
  seeded 49 settings): run #1 backup_freshness FAIL/CRITICAL + incident +
  exactly one incident.opened outbox row -> run #2 same incident id (dedupe)
  -> diagnose PENDING_MANUAL "AI_PROVIDER_ENABLED=false" (fail-closed);
  circuit-breaker and unsafe-action-refusal covered by tests; redaction
  order fixed (credentialed URLs before bare emails)
- failure_reason: —

## T-014 — Admin incidents console + CI stabilization (this round)

- goal: operator surface for the T-013 incident automation (list/detail/timeline/
  recovery display + manual close), and a fully green CI pipeline (test+e2e+
  security) — the first all-green CI run in repo history.
- inputs: docs/20, docs/12 (admin UI conventions), T-013 monitor, CI run
  43692491856/43692798617 logs
- acceptance_criteria: /admin/incidents lists monitor-managed incidents with
  status filter and severity/status tags; detail shows timeline (newest first),
  recovery actions and AI diagnosis entries; manual close is CSRF-protected,
  audited, timeline-recorded, and stops tracking (monitor opens a new incident
  on the next failure); cross-tenant requests 404; visual baseline added.
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED
- artifacts: `app/ui/admin.py` (GET /admin/incidents[/{id}], POST .../close),
  `app/templates/admin/incidents.html` + `incident_detail.html`, nav entry,
  `tests/test_incidents_ui.py` (7), admin-incidents visual baseline (+8
  re-synced baselines, byte-stable rendering), e2e server warm-up + 30s login
  timeout (CI cold-start fix), CI fixes from run-logs: real gitleaks v2 SHA
  (security job had never run — unresolvable pin since T-003) and psycopg
  scheme conversion in the e2e scratch-db step
- verification_evidence: local 179/179 (ruff clean; e2e layer 20/20);
  CI run bd723b9: test SUCCESS + security SUCCESS (first time), e2e
  10/11 with the sole failure the first-login cold start on the 2-core
  runner (TimeoutError >10s) — fixed by warm-up + 30s; run 9a82b3a: test
  SUCCESS (clean-runner manifest fix proven), security/e2e failures
  root-caused from logs and fixed in bd723b9. Two more runner-stall
  iterations (8f7d14f retry; c84bf15 already-logged-in guard — the retry
  itself induced a failure because /login 302s authenticated users, so a
  late-completing first attempt made attempt-2 land on /admin) produced
  the FIRST ALL-GREEN PIPELINE at run 43694546044 (c84bf15): test + e2e
  + security all success
- failure_reason: —

## T-015 — Sandbox-rollback recovery + whole-repo lint parity (this round)

- goal: recover from a full sandbox rollback (the working clone, venv and
  PAT file were wiped; everything of value was already on GitHub), then
  clear the whole-repo lint debt CI was not covering.
- inputs: scripts/restore_and_audit.sh (T-002 tooling), run logs of
  `ruff check .` vs CI's `ruff check app tests`
- acceptance_criteria: repo restored at a622704 and synced; venv rebuilt;
  chromium reinstalled; 179/179 local suite green (visual baselines
  byte-stable); authoritative audit clean; `ruff check .` fully clean;
  CI lint scope tightened to the whole repo.
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED
- artifacts: 34 auto-fixed findings (I001 import order, UP007/UP035 typing
  modernization, F401, RUF100) across alembic/env.py + 4 migration files
  + infra/dependency_audit.py; 3 manual fixes (BLE001 noqa with reason,
  SIM102 merged condition, ISC004 parenthesized concat); ci.yml lint step
  `ruff check app tests` -> `ruff check .`
- verification_evidence: restore_and_audit.sh replay (public mode,
  EXPECT overrides) brought the clone back at a622704; full pytest 179/179
  after migration-file lint edits (alembic upgrade head exercised by the
  e2e fixture); infra audit tool still reports 81 installed / 0 CVE /
  0 unused / 0 undeclared / 0 unresolved
- failure_reason: —

## T-016 — Founder credentials wiring + Telegram live attempt (this round)

- goal: wire the founder's uploaded credential sheet into the platform
  (gitignored .env, never committed) and attempt live Telegram delivery.
- inputs: upload/aknja-credentials.txt (via scripts/build_env.py mapper),
  docs/39, .env.example slot map
- acceptance_criteria: .env generated 600/gitignored with every sheet value
  mapped to its platform slot; Settings accepts TELEGRAM_FOUNDER_CHAT_ID as
  an alias of TELEGRAM_ADMIN_CHAT_ID; live send-test-notification executed.
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED (platform side) / EXTERNALLY BLOCKED (live delivery)
  RESOLVED same day: founder supplied a fresh token; getMe 200 OK
  (@agent_os_2026_bot, id 9258786244); governed send-test-notification
  delivered a real message (ref a7c-4479e486c10e) and the outbox drained
  to zero pending — docs/39 control plane fully live.
- artifacts: scripts/build_env.py (sheet→.env mapper, values never printed),
  scripts/live_ops.py (pgserver-backed live CLI driver), config.py
  AliasChoices + populate_by_name, tests/test_config_env.py (3)
- verification_evidence: 18 tests green (alias + notifications); live run:
  outbox enqueued → real Telegram API round trip → 401 Unauthorized (also
  confirmed by direct getMe curl with the exact .env token; token shape
  valid 46-char bot_id:hash) — the token is dead/revoked on Telegram's
  side, platform chain (alias→.env→outbox→API→terminal FAILED + audit)
  worked exactly as designed. Founder needs a fresh @BotFather token.

## T-017 — LLM provider live activation + inference hardening (this round)

- goal: activate the sheet's LLM keys through the audited registry path and
  produce the first REAL benchmark evidence run.
- inputs: GEMINI (main+backup)/GROQ/CEREBRAS/OPENROUTER/MISTRAL/HF keys,
  docs/41 §9 workflow, docs/33 worksheet rules
- acceptance_criteria: providers verified+enabled only via verify-provider
  with recorded evidence; at least one real completion through the governed
  layer; a completed real benchmark record.
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED (openrouter live; region/plan blocks documented for others)
- artifacts: openrouter+mistral adapters (`_openai_compatible`-based, :free
  slug rule enforced), config fields, default models (gemini-3.8-flash after
  live 404 retirement of 2.5-flash; inclusionai/ling-3.2-flash:free as the
  live-proven openrouter default), tests (4 incl. budget guard), total
  request-budget stream guard in `_request_json` (live finding: a :free
  model trickled one completion 7+ minutes — per-read timeouts cannot bound
  trickling streams; now every provider call is streamed under one
  wall-clock budget, retryable so failover moves on)
- verification_evidence: registry verified+enabled: gemini(250/day
  conservative)/groq(1000/day)/openrouter(50/day)/mistral(1000/day) with
  full evidence strings in the audit ledger. Live probes: gemini key valid
  but region-blocked (400 FAILED_PRECONDITION 'User location is not
  supported'); groq key valid but edge-403; cerebras edge-403; mistral key
  valid but x-ratelimit-limit-req-minute: 0 (plan has no chat quota);
  openrouter LIVE: governed llm-ping PONG 1434 ms (quota→audit→call log);
  FIRST REAL BENCHMARK record 1f67d6fc (openrouter/ling-3.2-flash:free):
  classification 100% PASS (4/4), translation 75% FAIL (floor 100%, one ml
  scenario) → §6 gate active for translation until a passing re-run.

## T-018 — Offsite backups on Cloudflare R2 (docs/22 §5A) (this round)

- goal: implement + live-verify offsite backup copies to the verified R2
  candidate without adding boto3 to the dependency surface.
- inputs: R2 S3 credentials (access key/secret/bucket) from the founder
  sheet, docs/22 off-host copy requirement
- acceptance_criteria: push (dump+manifest) and offsite restore drill
  working against real R2; unit tests for signing/roundtrip/tamper; new
  columns migrated.
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED
- artifacts: app/modules/ops/offsite.py (hand-rolled SigV4 + upload/download/
  push/pull with audit `backup.offsite_pushed` + idempotent double-push
  guard), migration e5f7a1b3c9d2 (backup_records.offsite_key/offsite_at),
  CLI `aknja backup push` / `backup offsite-drill`, tests/test_offsite.py (4
  incl. SigV4 golden pin + tamper rejection)
- verification_evidence: LIVE R2 roundtrip 2026-11-15 — push OK (dump +
  manifest to backups/ prefix), download OK (sha256 verified, manifest
  present), isolated offsite restore drill PASSED in 234 ms
  (counts/schema/audit_chain ok). Note: the sheet's bucket name
  `agency-artifacts` does not exist in the account (NoSuchBucket; the S3
  token also lacks CreateBucket rights) — the existing
  `aknja-digital-artifacts` bucket (documented default) is used instead;
  founder may rename later. Full suite 189/189 with the new columns.

## T-019 — Modal token verification + hosting path (this round)

- goal: verify the founder's Modal token and record the staging path it
  unlocks.
- inputs: MODAL_TOKEN_ID/SECRET from the sheet, docs/19 + docs/38 hosting
  admission
- acceptance_criteria: token authenticates against api.modal.com.
- deadline: — · idempotency_key: (this commit)
- status: COMPLETED (verification) / staging deployment awaits founder go
- artifacts: none in-repo (scratch venv /tmp/modal-venv; token stored in
  gitignored .env as MODAL_TOKEN_ID/MODAL_TOKEN_SECRET per .env.example)
- verification_evidence: `modal token set` verified the token against
  https://api.modal.com; `modal profile current` → workspace `sanjayaluva`.
  No OCI credentials exist in the sheet, so T-009 (OCI Always-Free staging)
  stays open; Modal is the verified alternative (web deployment of the
  FastAPI app + bundled PostgreSQL per docs/19 admission checklist).

## T-020 — Free-tier sweep after Mistral retirement + OCI deployment plan (this round)

- goal: respond to the founder's 2026-11-15 decisions (drop Mistral, drop
  Modal, OCI chosen, default R2 bucket) with a verified free-tier catalog
  and a deployment plan; answer the Malayalam-translation free-resource
  question.
- method: web sweep (sources recorded in docs/34 §3) + workspace audit for
  the OCI credentials.
- decisions:
  - Mistral withdrawn (provider removed the La Plateforme free tier).
  - Modal withdrawn from hosting (paid; one-time credits only).
  - OCI chosen: 2 x A1-class instances (1 OCPU/6 GB/50 GB) — docs/43.
  - Deploy path: GitHub Actions CI/CD over SSH (repo is public → standard
    runners free); direct SSH stays ops-only. docs/43.
  - R2: default bucket `aknja-digital-artifacts` stays; new-bucket creation
    documented (dashboard or Admin Read & Write token).
  - Malayalam translation: primary = self-hosted IndicTrans2
    en-indic-dist-200M (MIT, ~1.1 GB, en->ml) on instance 2; Gemini free
    tier for LLM-quality translation; Bhashini/Sarvam/Google Cloud
    Translation as benchmark/paid-adjacent candidates; NLLB-200 EXCLUDED
    (CC-BY-NC); bodhan-ai/indic-translate EXCLUDED (24 GB GPU + hosting
    sign-off clause); HF serverless inference no longer a free production
    path (credits).
- findings: the OCI username/IP/private key shared earlier did NOT reach the
  workspace (absent from .env, upload/, git history) — re-share requested;
  safe path: paste in chat or upload/oci_key.pem (*.pem gitignored).
- deliverables: docs/34 §3 (2026-11-15 watchlist + exclusions/withdrawals),
  docs/33 compute-list updates, docs/43 (OCI hosting + CI/CD plan),
  STATUS.md updates.
- status: COMPLETED (research + plan) / OCI EXECUTION BLOCKED on credential
  re-share.

## T-021 — R2 permission check + OCI credentials + production deploy (this round)

- goal: verify the founder's R2 permission update; SSH both OCI instances;
  bootstrap production on instance 1 per docs/43.
- inputs: re-uploaded `upload/aknja-credentials.txt` (workspace upload/,
  local git only — no remote; not the app repo), OCI key extracted to
  gitignored `upload/oci_key.pem`.
- R2: same token as .env (fingerprints match) but now Admin-capable —
  ListBuckets 200; test-bucket create/visible/delete round-trip CONFIRMED.
  No .env change needed; default bucket stays.
- inventory: both instances aarch64; inst-1 Ubuntu 22.04.5 (py3.10),
  inst-2 Ubuntu 24.04.5 (py3.12); 1 OCPU each; in-OS iptables default
  REJECT except 22.
- deployed on inst-1: PG14 + role/db; uv CPython 3.12.16; uv sync --frozen
  --no-dev; alembic x5; aknja.service (uvicorn 127.0.0.1:8000); Caddy +
  auto-TLS aknja.pp.ua; iptables 80/443 persisted; notifications timer
  (*/5min) + backup timer (02:30 UTC create→push→prune).
- verification: https://aknja.pp.ua/healthz → 200
  {"status":"ok","version":"0.1.0","env":"production"}, TLS valid,
  308 http→https, OCI security list 80/443 confirmed open.
- incident+fix: .env builder password re-parse bug (split(':')[-1] →
  "5432/aknja") corrupted .env.production on re-run → alembic 28P01 auth
  failure; fixed parse + idempotent ALTER ROLE sync; creds regenerated;
  migrations clean. Lesson recorded: generated-secret re-parse must use
  structured extraction, and db/env phases must force-sync the role.
- deliverables: infra/oci/ (7 deploy artifacts), scripts/t021a–t021f,
  docs/43 deployment record, STATUS.md LIVE row.
- status: COMPLETED — production LIVE; instance-2 + CI/CD workflow next.

## T-022 — production login provisioning + verification

- context: founder asked for user login credentials. Public login attempt
  returned 401 — root cause: the super admin is NOT auto-created on
  startup; it is a CLI step (`python -m app.cli create-super-admin`) that
  dev had run but the prod bootstrap had not.
- fix on prod (scripts/t022a_provision_admin.py):
  create-super-admin (founder@aknja.internal, tenant
  50315d27-b612-4a1c-b35d-d927b7fa290c) + `seed` (49 settings, 10
  capabilities, 5 tools) + `import-taxonomy` (19 families, 76
  subcategories, 224 services) — dev parity.
- verification (public): POST /api/v1/auth/login → 200 SUPER_ADMIN session
  cookie; GET / → 302 /admin; GET /admin → 200 "Overview — Aknja Digital".
- facts: exactly ONE login exists today (the founder super-admin;
  BOOTSTRAP_ADMIN_* in .env / .env.production). No user-management or
  client-portal account flow in the console yet — additional users would
  need a CLI `create_user` path or a future console feature.
- ops note: deploy runbook for new instances must include the three CLI
  provisioning steps after migrations.
- status: COMPLETED.

## T-023 — Translation ungated: IndicTrans2 worker + task-scoped routing + instance-2 + CI/CD (this round)

- founder decisions honored: aknja.pp.ua is the FINAL domain for now
  (aknja.in cutover deferred until stable — recorded in docs/19); complete
  the requirement-doc open items.
- app: `admit_usage(task=...)` implements the docs/13 classify step —
  products with `capability_contract["tasks"]` serve ONLY those tasks and
  never generic traffic; indictrans2 adapter (OpenAI-compatible worker
  shim) + candidate entry; groq default model fixed to `openai/gpt-oss-20b`
  (llama defaults retired, live 404); tests +6, suite 175 green; ruff
  import-order fix (CI caught what the recycled sandbox missed — ruff is
  now part of the local pre-commit habit).
- worker (infra/oci/worker/): IndicTrans2-dist-200M en<->{ml,hi,ta};
  Devanagari script-unification conversion (indicnlp), brand preservation
  via startup-calibrated stems + glossary; transformers pinned 4.38.2
  (5.x broke the custom code: transformers.onnx removed; beam-search cache
  shape); validated 8/8 over HTTP locally BEFORE deployment.
- instance-2: staging (PG+app, tunnel-only access) + worker + reverse SSH
  tunnel to inst1 (restricted key, no security-list change).
- prod: candidates registered; openrouter/groq/indictrans2 FREE_VERIFIED
  (allowances 50/1000/5000 per day, conservative/self-imposed); gemini
  DISABLED with audit — generateContent region-blocked from sandbox (400)
  and OCI (silent drop); live pings: openrouter PONG 2594 ms, groq PONG
  370 ms, indictrans2 3838 ms (full Malayalam translation).
- benchmarks (prod, honest): openrouter FULL 36 scenarios — 68% overall,
  PASS classification/summarization/requirements/qa_review, FAIL
  translation 50% / code_review 50% / proposal_draft 25% → gate active
  for those (record 0979448a). indictrans2 translation 100% PASS 8/8
  (record d665d003) → TRANSLATION UNGATED; non-targeted routing proof:
  llm_complete(task=translation) auto-selects indictrans2 (4.5 s, brands
  preserved).
- CI/CD: deploy.yml (workflow_dispatch) + restricted ed25519 deploy key
  (command= wrapper, sha-only) + GitHub secret OCI_DEPLOY_KEY (libsodium-
  sealed); full-path deploy run: success (1b6c8b8); wrapper healthz retry
  fixed (curl race at 3 s).
- DR: prod offsite restore drill PASSED (isolated scratch DB; aknja role
  granted CREATEDB); instance-2 cross-host R2 pull + sha256 match.
- incident notes: llm-ping prompt must be target-language shaped (worker
  contract); deploy wrapper healthz race (fixed); sandbox `source .env`
  broke on unquoted spaces → false "invalid key" during gemini debugging.
- status: COMPLETED — translation live via self-hosted free path.

## T-024 — Ops round: uptime fix, real allowances, bucket rename, audit-chain repair (this round)

- founder replies honored: (2) UptimeRobot done — verified probing but our
  GET-only /healthz answered 405 to their HEAD probes (monitor read DOWN);
  HEAD route added (57281f6), public HEAD → 200, monitor green.
  (3) console numbers NOT needed — real limits read from live APIs:
  groq 1000 rpm/8000 tpm headers; openrouter /api/v1/key free-tier
  confirmation (50/day documented stands). (4) bucket renamed to
  aknja-artifacts (already existed, owned by us), both .envs switched,
  fresh backup pushed + drill PASSED, old aknja-digital-artifacts
  emptied and deleted.
- sandbox recycle recovery: SSH key re-extracted from the credentials
  file (upload/ restored), instance .envs pulled back, repo reset to
  origin/main. t023 scratch scripts lost (logic lives in the app repo).
- sign_v4 canonical query-string fix + list_objects (268f5a0): every
  S3 request WITH a query previously failed 403 SignatureDoesNotMatch
  (found live during the migration); golden pin + order-insensitivity
  + parsing tests.
- AUDIT-CHAIN INCIDENT (found by the restore drill): record_audit read
  the chain tail without a lock — the parallel benchmark runs of T-023
  forked the hash chain (breaks at ids 37/40); every later drill failed
  (counts=ok schema=ok audit_chain=BROKEN). Fix: pg_advisory_xact_lock
  in record_audit (993074f) + 4-thread concurrency test. Prod repair:
  deterministic full-pass relink (18 rows) through the documented
  aknja.audit_admin escape hatch, surgery recorded as an audit event,
  fresh backup → push → offsite-drill PASSED.
- gemini comparison: direct API region-blocked (product disabled,
  T-023g); openrouter free pool currently has NO gemini :free (14 free
  models, closest Google = gemma-4-26b/31b-it:free); the gemma-4-31b
  translation probe hit the exhausted :free daily budget (8×429).
  Deferred with the evidence recorded (docs/33).
- status: COMPLETED — translation live (indictrans2 8/8), monitors
  green, bucket consolidated, chain healthy, allowances evidence-based.

## T-024f — Gemini re-diagnosis: misdiagnosis corrected, provider re-enabled (this round)

- founder's home curl test decoded: the 403 was a typo'd header (no-key
  response); the hang on the correct call matched OCI. Five-probe matrix
  from Mumbai: key VALID, India NOT blocked, gemini-3.x-flash free-tier
  capacity-starved (non-streaming black-hole vs honest streaming 503);
  sandbox HK egress is the actually-blocked network (source of the
  T-023g misdiagnosis).
- two real app bugs fixed: gemini adapter parsed gemma-4 thought parts
  as the answer (12% translation score was pure parsing); default model
  gemma-4-31b-it too slow (15s PONG) -> gemma-4-26b-a4b-it (2s PONG).
- provider re-enabled with audited evidence; ping OK 2683 ms.
- deferred comparison CLOSED: translation 0/8 vs indictrans2 8/8 —
  IndicTrans2 wins decisively. Full benchmark: requirements + code_review
  75% PASS each -> gemini UNGATED for those two tasks (third live pool
  lane); other tasks gated pending flash capacity.
- status: COMPLETED — gemini is a live, honestly-gated pool member.

## T-025 — client translation, gate self-lock fix, full e2e sweep (this round)

- client-facing translation feature SHIPPED (the last deferred service
  item): portal /portal/translate through the governed gateway; daily
  limit + credential screen + hash-only audit. 6 unit tests + real
  browser e2e.
- incident + fix: quality gate blocked its own re-measurement (concurrent
  benchmark launches produced 0% rows of gate-blocked scenarios that
  locked groq/openrouter). llm_complete(bypass_quality_gate=True) for the
  benchmark path; regression-tested.
- AI-workflow e2e for both domains, all 7 task profiles, real provider:
  dedicated run 4/4 PASSED (every task produced a real output through the
  governed path). Full-suite final run: 209 passed, the last AI test hit a
  transient openrouter UPSTREAM throttle (limit_source:
  upstream_provider_shared_pool, retried separately).
- platform e2e: flows 11/11, visual 9/9 (providers baseline refreshed).
- prod clean re-runs (gate-bypass build): groq 54% CONCLUSIVE (code_review
  75% PASS); openrouter re-run landed in another upstream throttle window —
  recorded INCONCLUSIVE (36/36 provider errors) and did NOT poison the gate;
  gemini re-benched on the current default model: 57% CONCLUSIVE
  (summarization + code_review 75% PASS each).
- one-time data repair: 10 benchmark rows from the incident window (>=50%
  provider-error scenarios, recorded before the inconclusive flag existed)
  reclassified as inconclusive so the gates fall back to honest verdicts.
- LIVE POOL after the round (conclusive evidence only):
  translation=indictrans2 (100%), classification=openrouter (100%),
  summarization=openrouter+gemini (75% each), requirements=openrouter (100%),
  qa_review=openrouter (75%), code_review=groq+gemini (75% each),
  proposal_draft=none (all free models <75% floor -> fail-closed to the
  human queue, by design).
- portal translation prompts now match the indictrans2 worker contract
  verbatim (benchmark instruction strings; en<->{ml,hi,ta} pairs only,
  enforced at the form). Production-verified in all four directions.
- status: COMPLETED

## T-026 — catalog->delivery flow, both-domain dogfood, quota ledger fixes (this round)

- BUILT: service items carry delivery blueprints (SE + DM domains, 224
  items stamped); start project from catalog (admin UI + service layer);
  governed AI task execution with inline artifacts; human-verify state
  machine (AI -> REVIEW, never auto-DONE); CLI stamp + truthful promotion.
- TESTED: 7 unit tests + real-browser e2e driving BOTH domains end-to-end
  (catalog item -> project -> REAL AI artifact -> portal), 195 unit tests
  green, CI green.
- DOGFOOD LIVE: two real projects on prod (Showcase App SE + Launch
  Marketing DM) with real AI artifacts (code review via groq, Malayalam
  campaign copy via indictrans2).
- FIXED (found by the dogfood): reservation settle/release never wired
  (337 phantom reservations hard-stopped the whole pool); ping daily-usage
  carry across UTC midnight; gate conclusive window too narrow; JSONB
  same-object repair no-op.
- status: COMPLETED (openrouter hard-stop tail noted in docs/33)

## T-026 final — full automation + readiness smoke 8/8 (this round)

- CI-green auto-deploy (workflow_run, tested 3x live), aknja-ping timer
  (4h snapshot refresh), 90s LLM budget for real slow free-tier
  generations, per-project task idempotency, pool-mode skip refund on
  the failover budget.
- prod readiness smoke 8/8: full service-provider lifecycle live.
- status: COMPLETED — system open for real client testing

## T-027 — credential hub, unified intake, per-product models (docs/34)

- integration_credentials (Fernet, DB-first resolution, env = DR seed),
  /admin/integrations CRUD + live test (pass = activation gate, fail =
  ACTIVE->FAILED), intake_messages + /admin/intake (MANUAL channel live,
  AI classification -> extraction -> lead + telegram notify, verbatim
  provenance), provider_products.model admin-editable.
- Live: gemini key hub-managed + ACTIVE; Malayalam WhatsApp intake
  converted to lead + notified; gemini-3-flash-preview verified as alt
  (2.5 line retired 404); smoke 8/8; suite 207 green.
- Phases next: T-028 email poller, T-029 telegram inbound, T-030
  whatsapp cloud, T-031 voice, T-032 github tooling, T-033 multi-service
  plans (docs/34 §1 table).
- status: COMPLETED
### T-028/029 ops notes (live)

- aknja-email.timer installed and RUNNING (5-min cadence; no-op until an
  ACTIVE EMAIL credential exists). Root cause found while wiring it: the
  deploy command= wrapper is a fixed copy at /home/ubuntu/aknja-deploy.sh
  and repo edits to it did not apply — the wrapper now self-syncs from
  the repo as the last step of every healthy deploy (one manual bootstrap
  was needed to install the self-syncing version).
- Prod verified: webhook 404 fail-closed, poll-email no-op summary,
  telegram-set-webhook exit 1 without an ACTIVE credential, wrapper ==
  repo, smoke 8/8 (f1125ed).

## Open items (next rounds)

- DONE T-024f: gemini re-enabled (gemma-4-26b-a4b-it default) and
  ungated for requirements + code_review; flash-line capacity retest
  whenever ping goes slow again (streamGenerateContent surfaces the
  honest 503)
- DONE T-025: groq + openrouter full benchmarks re-run cleanly on the
  gate-bypass build (single sequential launch; per-task gates now reflect
  honest fresh evidence)
- DONE T-024: UptimeRobot live — founder account connected, probing
  https://aknja.pp.ua/healthz (~5 min, multi-IP); our GET-only route
  answered 405 to their HEAD probes, fixed with an explicit HEAD route
  (57281f6), monitor green since
- DONE T-024: bucket renamed aknja-artifacts; old bucket deleted
  (retired the old agency-artifacts/aknja-digital-artifacts naming)
- DONE T-025: client translation LIVE at /portal/translate (governed
  gateway path, daily limit, credential screen, hash-only audit)
