# Episodic memory — LLM inference layer + orchestrator integration (2026-11-14)

**Scope:** EPISODIC · **Sensitivity:** INTERNAL · **Approved:** yes (founder-reviewed)

## What was built

1. **Inference layer** (`app/modules/ai/inference.py`): 7 task profiles
   (classification, translation, summarization, requirements, code_review,
   proposal_draft, qa_review); HTTP adapters for groq / github_models /
   gemini / cloudflare_workers_ai — no vendor SDKs; per-attempt quota
   admission; audited failover on 429/5xx (failed provider excluded, free
   pool exhausted before stopping); fail-closed PENDING_MANUAL when nothing
   is verified. `llm_call_logs` stores provider/model/latency + prompt HASH
   only. `llm-ping` CLI is the v5.3.2 §8 "Test provider" action.
2. **Orchestrator integration** (`execute_llm_step`): LLM steps legal only in
   PLAN / EXECUTE_LOW_RISK / EXECUTE_APPROVED; capability must allow
   `llm.generate`; run data class must be PUBLIC/INTERNAL. Outcomes:
   SUCCEEDED → event + audit, run stays in its execution state (a model
   response is never a completed action); PENDING_MANUAL → BLOCKED (founder
   queue; RETRY_WAIT from EXECUTE_APPROVED since BLOCKED is unreachable
   there); FAILED → RETRY_WAIT.

## Lessons worth remembering

- Writing the gateway test for `llm.generate` exposed that
  `allowed_data_classes` was stored but never enforced — the Tool Gateway
  now enforces it, so CONFIDENTIAL/RESTRICTED data can never egress to a
  third-party model. Tests that expect a block are how such gaps surface.
- `seed_capabilities` returns only NEW rows; on an already-seeded DB query
  the capability instead of using the return value.
- The audit ledger is hash-chained and stores payload hashes only — assert
  on action + resource binding, never on `payload` content.

**Provenance:** commits 005aee9 + this round; `tests/test_ai_inference.py`
(8), `tests/test_orchestrator_llm.py` (6); migration `b3f1a9c2d4e5`;
runbook §10; docs/09.
