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

## Open items (next rounds)

- T-006 (candidate): Telegram delivery wiring (token unset, stub present)
- T-007 (candidate): Playwright E2E + visual comparison (docs/16)
- T-008 (candidate): benchmark runner for ml/en/hi/ta quality floors (v5.3.2 §6)
- T-009 (candidate): staging provisioning on OCI Always-Free ARM (SRS §2.1 erratum)
