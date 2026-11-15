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

## Open items (next rounds)

- T-009 (candidate): staging provisioning on OCI Always-Free ARM (SRS §2.1 erratum)
