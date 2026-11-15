# Episodic memory — LLM quality benchmark runner (2026-11-14)

**Scope:** EPISODIC · **Sensitivity:** INTERNAL · **Approved:** yes (founder-reviewed)

## What was built

The v5.3.2 §6 quality-preservation loop for the free LLM pool:
`app/modules/ai/benchmark.py` holds a versioned 36-scenario bank (7 task
profiles × ml/en/hi/ta; 2 scenarios each for classification/translation,
1 for the generative tasks), deterministic evaluators, per-task floors
(classification + translation 1.0, generative 0.75 — one weak language
tolerated), `run_benchmark` (targeted, no failover) persisting one
`provider_quality_benchmarks` row per run (migration `d8e3f6a7c2b4`), a
`benchmark.failed` founder alert, and `benchmark_gate` wired into
`llm_complete`: a fresh FAILED benchmark blocks the provider for exactly
the failed tasks; passed/stale(>30d)/unbenchmarked/uncovered tasks stay
eligible. CLI: `run-llm-benchmark --provider X [--tasks] [--languages]`,
exit 0 only on a passing floor run.

## Lessons worth remembering

- Deterministic floors, not LLM-judged factuality: scoring is code-only
  (JSON validity, label match, entity/script preservation, key facts,
  length bounds, sections). Golden-answer classification and terminology
  preservation are strict (1.0); generative tasks get 0.75 so one weak
  language out of four fails but a single slip doesn't.
- Circular import discipline: inference.py imports `benchmark_gate` at
  module level, so benchmark.py must import inference ONLY inside
  functions (llm_complete, _target_product).
- Scenario instructions are self-contained per language — the provider
  must follow instructions IN the benchmark language, which is the point
  of language quality; brand entities stay Latin ('Aknja Digital') and
  the script check tolerates that (≥50% target-script letters).
- Benchmark evidence must be real: the CLI evidence run used a dummy
  Groq token and recorded the genuine HTTP 403 per scenario — a FAILED
  benchmark from real egress, not a fabricated pass.
- Gate freshness: a failed benchmark stops gating after 30 days (stale
  evidence must not block forever); re-run the benchmark instead.

**Provenance:** this round's commit; `tests/test_benchmark.py` (16,
suite 132); migration roundtrip check; docs/26 + runbook §13.
