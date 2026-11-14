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
| Hugging Face Spaces | hosting/compute | SRS §8.2 staging profile `UNIFIED_STAGING_HF_NEON` (HF Docker Space, 16 GB RAM) | docs/33: distinguish free static hosting from compute-backed hardware pricing |
| Cloudflare Pages | hosting/compute | docs/33 ("Cloudflare Pages/R2: verify limits...") | verify limits, billing behavior, current plan |
| Jina Reader | search | SRS §7 anti-ban guard ("rate-limited Jina Reader endpoints") | read-only ingestion, rate-limited; no automated form-filling/bot-bidding |

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
