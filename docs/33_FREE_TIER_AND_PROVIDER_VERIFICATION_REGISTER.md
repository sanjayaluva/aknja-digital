# Free Tier and Provider Verification Register

This is a verification worksheet, not a promise of free entitlements.

For each account/product record the official pricing/docs URL, account region, current plan, free quota, reset window, restrictions, commercial-use rights, payment method presence, auto-upgrade behavior, usage API availability, metrics delay, data retention, privacy, verified date and reviewer.

Candidate compute:
- OCI A1: CHOSEN 2026-11-15 as the free hosting base — founder provisioned 2 x A1-class instances (1 OCPU / 6 GB / 50 GB each); on first access confirm Always Free/idle reclamation conditions, volume quota and aarch64 arch (docs/43).
- GitHub Actions: check included minutes/storage by repository visibility and plan.
- Colab/Kaggle: interactive/best-effort GPU sessions; no durable service guarantee; checkpoint jobs.
- Google Cloud/AWS: eligibility, region and credits vary; do not rely on trial credits as perpetual free.
- Cloudflare Pages/R2: verify limits, account billing behavior and current plan.
- Neon/Upstash: verify account plan, usage metrics and payment-method upgrade behavior.
- Hugging Face: distinguish free static hosting from compute-backed hardware pricing.
- Mistral La Plateforme: free tier removed by the provider (2026-11-15) — not a candidate.
- Modal.com: paid hosting; withdrawn 2026-11-15 (one-time trial credits only).
No external provider should be enabled until evidence is recorded. A provider can be removed from pool without affecting core platform operation.

## Verification round — 2026-11-15 (T-023g, prod/OCI egress)

- openrouter: FREE_VERIFIED, allowance 50/day (conservative; `:free` pool),
  live llm-ping PONG 2594 ms. FULL benchmark (record 0979448a): 68% overall
  — classification/summarization/requirements/qa_review PASS (floor met);
  translation 50%, code_review 50%, proposal_draft 25% FAIL → §6 gate
  active for those three tasks until a passing re-run.
- groq: FREE_VERIFIED, allowance 1000/day (conservative). NOTE: Groq
  retired the un-namespaced llama defaults (`llama-3.3-70b-versatile` AND
  `llama-3.1-8b-instant` → 404 model_not_found); live PONG with
  `openai/gpt-oss-20b` (370 ms) — new adapter default.
- gemini: FREE_VERIFIED + ENABLED (re-audited T-024f; allowance 200/day
  conservative). The earlier "region block" note was a MISDIAGNOSIS: the
  dev sandbox egresses from Hong Kong (blocked for every authenticated
  call, clean 400) while the OCI egress is Mumbai, where the key works.
  See the T-024f section below for the capacity/quality detail.
- indictrans2 (self-hosted, MIT): FREE_VERIFIED, allowance 5000/day
  (self-imposed rate protection) — worker on instance-2, reached via
  reverse SSH tunnel. Live ping 3838 ms; PROD translation benchmark
  (record d665d003): 100% PASS (8/8, floor 1.0) — translation UNGATED.

## Real-allowance round + uptime + bucket — 2026-11-15 (T-024)

- groq: REAL limits read from live response headers (T-024a):
  1000 requests/min + 8000 tokens/min on openai/gpt-oss-20b; registry
  allowance stays conservative 1000/day (evidence in the audit ledger).
- openrouter: /api/v1/key confirms is_free_tier=true, usage 0; provider
  exposes no programmatic daily cap; documented 50/day stands (the pool
  exhausted it 2026-11-15 after the 44 benchmark calls — every further
  :free call 429s until the daily reset).
- gemini: still DISABLED (region). Gemini-free comparison attempted via
  openrouter: no gemini :free model in the current 14-model free pool;
  closest Google models are google/gemma-4-26b/31b-it:free — the 31b
  translation probe hit the exhausted :free budget (8/8 HTTP 429).
  Retry after the UTC daily reset or when a gemini :free appears.
- uptime: founder signed up UptimeRobot (probing ~5 min, multi-IP);
  our GET-only /healthz answered 405 to their HEAD probes (read as
  DOWN) — fixed with an explicit HEAD route (57281f6), monitor now green.

## Gemini re-diagnosis + provider re-enable — 2026-11-15 (T-024f)

Trigger: the founder ran the home-network curl test. Command 1 (correct
`x-goog-api-key` header) returned NOTHING in 15s; command 2 used a typo'd
header (`x-google-api-key`), so the fast 403 was only the no-key response,
not a verdict on the key. Five-probe matrix from OCI Mumbai decoded it:

| probe | result |
|---|---|
| models list, key | 200 — key VALID, India NOT blocked |
| generateContent gemini-3.8-flash / 3.6 / v1 path / http1.1 | black-hole, >120s no response |
| streamGenerateContent same model | fast honest 503 "high demand" |
| gemma-4-31b-it generateContent | 200, but 15s for a PONG (thinking preamble; thinkingBudget=0 rejected 400) |
| gemma-4-26b-a4b-it generateContent | 200, 2s PONG — the working default |

Verdict: the free-tier gemini-3.x-flash line is capacity-starved; the
non-streaming endpoint black-holes instead of erroring (Google-side
degradation). The sandbox egress (HK) is separately region-blocked with a
clean 400 — the source of the original misdiagnosis.

Fixes shipped: gemini adapter now skips gemma-4 "thought" parts (a live
translation run scored 12% purely from parsing the thinking preamble;
+test), default model -> gemma-4-26b-a4b-it. Provider re-enabled with
audited evidence; llm-ping OK 2683 ms.

Benchmarks (records 730c4974 translation-only, c7d5113e full):
- translation 0/8 vs indictrans2 8/8 — IndicTrans2 DECISIVELY wins the
  deferred comparison; gemini stays gated for translation.
- requirements 75% PASS and code_review 75% PASS -> UNGATED: the pool now
  has a third live lane (groq all tasks, openrouter partial, gemini
  requirements+code_review).
- classification 62%, summarization 0%, proposal_draft 25%, qa_review 50%
  -> gated until a passing re-run (flash capacity may change this).

## Client translation + gate self-lock fix + AI-workflow e2e — 2026-11-15 (T-025)

- client-facing translation LIVE (portal /portal/translate): walks the
  ToolGateway llm.generate path (data-class screening, quota, tool audit),
  client daily limit 50/day (audit-counted), credential-shape screen,
  hash-only audit (raw text never persisted). Unit tests 6/6; browser e2e
  with a REAL provider passed.
- GATE SELF-LOCK BUG (live incident): three concurrent benchmark launches
  (two SSH-channel timeouts had silently started the processes) produced,
  after the FIRST real groq run scored an honest 52% (21/36), two more runs
  whose every scenario was gate-blocked -> 0% rows of self-referential
  evidence that locked groq + openrouter out of all tasks. Fix (d9b5401):
  the benchmark runner passes bypass_quality_gate=True — the gate is fed BY
  benchmarks and must never block the re-measurement. Regression test
  covers bad-run-gates -> good-re-run-lifts.
- AI-workflow e2e (tests/e2e/test_e2e_ai_workflows.py): real input ->
  governed inference -> real output for ALL SEVEN task profiles across both
  domains (DM: translation via the portal page, classification,
  summarization; SE: requirements, code_review, qa_review, proposal_draft)
  with a real free provider. Free-tier upstream throttling handled by
  pacing + governed-retry pauses.
- providers.png visual baseline refreshed (stale since T-023 added the
  indictrans2 candidate rows).
