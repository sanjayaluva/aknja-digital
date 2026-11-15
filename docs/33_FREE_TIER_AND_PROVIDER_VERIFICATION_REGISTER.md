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
