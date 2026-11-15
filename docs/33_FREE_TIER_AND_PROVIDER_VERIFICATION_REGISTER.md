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
- gemini: DISABLED (audited). generateContent is region-blocked for this
  account from BOTH the dev sandbox ("User location is not supported",
  400 FAILED_PRECONDITION) and the OCI egress (silent drop → read timeout);
  the models metadata endpoint works, keys are valid. Re-verify from an
  allowed region before enabling; keys stay in settings.
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
