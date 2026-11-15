# Free Service Candidate Watchlist

Status: **worksheet** — same rule as doc 33: candidates are not entitlements.
Nothing here is enabled, promised, or relied upon until it is verified in the
actual account and activated through the audited `verify-provider` CLI step.

This register extends the doc-sourced pool (`docs/33`, `docs/source_provider_pools_v5.3.2.md`
§5, SRS §9) in two ways:

1. **Doc-sourced services that were missing from the seeded candidate pool**
   (all referenced in the package docs but not previously registered):

| Service | Category | Where the docs mention it | Constraint from the docs |
|---|---|---|---|
| Google Colab | hosting/compute | SRS §7 ("Colab/Kaggle are opportunistic batch compute, not durable production hosting"), SRS §8.4 `gpu_checkpoint_interval_min`, docs/33, docs/14 | interactive/best-effort GPU; checkpoint jobs; never upload confidential client assets |
| Modal.com | hosting/compute | SRS §8.4 Layer 4 ("Modal.com free credits") | docs/33: trial credits are one-time, never perpetual free |
| Cloudflare Pages | hosting/compute | docs/33 ("Cloudflare Pages/R2: verify limits...") | verify limits, billing behavior, current plan |
| Jina Reader | search | SRS §7 anti-ban guard ("rate-limited Jina Reader endpoints") | read-only ingestion, rate-limited; no automated form-filling/bot-bidding |

> **Withdrawn 2026-11-14 — Hugging Face Spaces (Docker/Gradio hosting).**
> HF moved Docker and Gradio Spaces to paid plans (PRO for personal, Team or
> Enterprise for organizations); only Static Spaces remain free
> (https://huggingface.co/docs/hub/en/spaces-overview). The SRS §2.1 staging
> profile `UNIFIED_STAGING_HF_NEON` (HF Docker Space host) is therefore no
> longer a zero-cost option — see the SRS §2.1 erratum. The `huggingface`
> registry account keeps only the serverless inference product.

2. **Web-researched watchlist (researched 2026-11-14)** — free tiers that
   exist on the public internet today and fit the existing category pools.
   Figures are point-in-time observations from public pricing pages, quoted
   with their source URL; re-verify in the account console before activation.

| Service | Category | Observed free tier (2026-11-14) | Source | Fit |
|---|---|---|---|---|
| Cloudflare Workers AI | AI/LLM | 10,000 Neurons/day, shared across models, resets 00:00 UTC | https://developers.cloudflare.com/workers-ai/platform/pricing | Layer-1 LLM pool member on the same Cloudflare account as R2 |
| GitHub Models | AI/LLM | free prototyping tier, per-minute/per-day request + token caps | https://docs.github.com/en/github-models | reuses the existing GitHub App credentials; testing allowance, not production |
| UptimeRobot | monitoring | ~50 monitors, 5-minute checks | https://uptimerobot.com/pricing | external `/healthz` uptime signal |
| Better Stack | monitoring | ~10 monitors, 3-minute checks, 1 status page | https://betterstack.com/pricing | alternative monitoring pool member |
| Brave Search API | search | ~$5 free monthly credits (~2,000 basic queries) | https://brave.com/search/api | lead-radar market research (anti-ban guard applies) |
| Tavily | search | 1,000 API credits/month, no card | https://www.tavily.com | LLM-oriented research endpoint for briefings |
| Redis Cloud | cache/queue | 30 MB Essentials, 100 ops/sec, 30 connections | https://redis.io/pricing | second cache pool member after Upstash |

## Deliberately NOT added

- **Google Cloud / AWS free trials** — docs/33: "do not rely on trial credits
  as perpetual free."
- **PlanetScale / ElephantSQL / Fly.io free databases** — free tiers for new
  accounts have been withdrawn or shut down over 2024–2025; the DB pool stays
  Neon / Supabase / OCI-hosted PostgreSQL.
- **Any paid tier of anything** — zero-cost mode (v5.3.1) blocks paid
  selection without an explicit founder override.

3. **Web-researched watchlist (researched 2026-11-15 — after the Mistral
   free-tier retirement)** — same rules: point-in-time observations with
   source URLs; re-verify in the account console before activation.

| Service | Category | Observed free tier (2026-11-15) | Source | Fit |
|---|---|---|---|---|
| Groq free tier | AI/LLM | per-model RPM/RPD/TPM/TPD quotas, no card | https://console.groq.com/docs/rate-limits | stays in the Layer-1 pool; key valid, region-blocked from dev sandbox only |
| Cerebras Developer tier | AI/LLM | per-model RPM/TPM quotas, no card | https://inference-docs.cerebras.ai/support/rate-limits | stays in the Layer-1 pool; key valid, region-blocked from dev sandbox only |
| Gemini API free tier (AI Studio) | AI/LLM | per-model RPD limits (tightened 2026-02) | https://aistudio.google.com/docs/rate-limits | strongest free Malayalam-capable LLM; key valid, region-blocked from dev sandbox only |
| AI4Bharat IndicTrans2 en-indic-dist-200M | translation (self-host) | MIT license, ~0.3B params, ~1.1 GB F32 weights, en→ml supported; gated download (HF account + accept terms) | https://huggingface.co/ai4bharat/indictrans2-en-indic-dist-200M | PRIMARY free translation path: self-host on the 2nd OCI A1 instance; commercial use allowed; CPU inference feasible for batch/UI strings |
| Bhashini (NLTM) | translation | free APIs covering the 22 scheduled languages incl. Malayalam; organization registration required; developer-tier usage is PoC-only | https://bhashini.gov.in + https://dibd-bhashini.gitbook.io/bhashini-apis | government translation path; production use likely needs Sahyogi partnership — benchmark/fallback only |
| Sarvam Translate | translation | ₹100 one-time signup credits (~50K chars at ₹20/10K chars); state-of-the-art Indian-language quality | https://www.sarvam.ai/api-pricing | trial credits are one-time, never perpetual free (same rule as Modal) — benchmark only |
| Google Cloud Translation | translation | 500,000 chars/month free (applied as a $10 monthly credit); commercial use allowed | https://cloud.google.com/products/translate/pricing | requires a GCP billing account (card on file) — conflicts with the zero-cost guard unless the founder explicitly accepts that condition |
| MyMemory | translation | ~5,000 chars/day anonymous; higher with a registered email | https://mymemory.translated.net/doc/spec.php | low-cost TM-based fallback for short strings |
| OCR.space | OCR | 25,000 requests/month, 500/day per IP, 1 MB / 3-page PDF cap | https://ocr.space/ocrapi | document-ingestion candidate for agency paperwork |
| Resend | email | 3,000 emails/month, 100/day, 3 inboxes | https://resend.com/pricing | transactional-email candidate alongside docs/39 paths |

Exclusions recorded 2026-11-15 (do not pool):

- **NLLB-200 family** — CC-BY-NC 4.0, non-commercial only
  (https://github.com/facebookresearch/fairseq/issues/5647); banned for
  client-facing translation.
- **bodhan-ai/indic-translate** — Indic Open Model License v1.0 permits
  commercial use but the 7.9B model needs a 24 GB+ GPU (15.9 GB bf16) and
  written sign-off to host as an API; infeasible on OCI A1 free instances.
- **Hugging Face serverless inference as a production path** — free users now
  need purchased credits; Hugging Face stays model-distribution +
  benchmarking only.

Withdrawn 2026-11-15:

- **Mistral La Plateforme free tier** — removed by the provider
  (community-corroborated, unrestored 1+ month at 2026-11-15); the mistral
  adapter stays in the codebase but no free pool entry remains.
- **Modal.com hosting** — paid (one-time trial credits only); withdrawn from
  the hosting pool by founder decision. The verified token stays unused.

## Standing rules (unchanged)

- v5.3.2 §5G still governs monitoring: security audit events live in the
  application database, never only in a free third-party plan; a monitoring
  outage must not disable the application.
- Provenance is recorded in each registry entry's `capability_contract`
  (`provenance: "docs"` or `"web:2026-11-14"`), so it is always visible which
  candidates came from the package docs and which from web research.
- Every entry seeds as FREE_UNVERIFIED + disabled with unknown allowance and
  fails closed until `python -m app.cli verify-provider` records the docs/33
  evidence.
