# 34 — Multi-Channel Intake, Credential Hub and Provider Independence (roadmap + T-027)

Status: T-027 foundation LANDED 2026-11-16; phases below are sequenced follow-ups.
Source: founder requirements brief (2026-11-16, "System Requirements and
Operational Workflow") reconciled against docs/01 MASTER SRS and the live system.

## 1. What the brief asks for, mapped to reality

| # | Requirement (brief) | System today | Gap → phase |
|---|---|---|---|
| 0 | Gmail under system name; register accounts on all free providers; credentials in DB, admin CRUD/test/activate, no hardcoding | LLM keys resolve from **env vars** (`_provider_key`, inference.py); Telegram out-bound key also env | **T-027 (this)**: encrypted `integration_credentials` table + admin Integrations page + DB-first resolution with env fallback |
| 1 | Multi-channel intake: phone, WhatsApp, Telegram, email, manual text, voice | manual only, via Leads form (no unified pipeline, no provenance) | **T-027**: unified `intake_messages` pipeline + manual channel + admin Intake page. T-028 email (Gmail IMAP/POP poller), T-029 Telegram bot inbound, T-030 WhatsApp Cloud, T-031 voice |
| 1.1 | Gmail / custom-domain email monitoring | none | T-028 (EMAIL credential type + poller; Gmail via app password, custom domain via IMAP) |
| 1.2 | Telegram bot inbound + admin commands | out-bound notify only (docs/39) | T-029 (bot webhook → intake; approval replies reuse docs/39 patterns) |
| 1.3 | WhatsApp inbound | none | T-030 (Cloud API webhook; needs Meta business verification) |
| 1.4 | Manual text input processed like automated messages | leads form only, no AI processing | **T-027**: Intake page → AI classification + requirements extraction → lead + admin notification, full provenance |
| 2 | Voice transcription (ML/EN) + requirement extraction + speaker ID | none | T-031 (TRANSCRIPTION credential type; Gemini audio or Whisper/Sarvam per SRS §; speaker ID only where provider supports) |
| 3 | Full I/O transparency + admin pause/verify/approve | audit events for every AI call, admin AI/approvals pages, REVIEW task states | **T-027**: intake records store raw input + channel + both AI outputs verbatim; every future channel reuses it. Approval gates already exist (approvals.html, task REVIEW) |
| 4 | Gemini high-capability models; provider-independent, admin-addable providers | model hardcoded per provider (`_default_model`); gemini stuck on `gemma-4-26b-a4b-it` after T-024f flash capacity starvation | **T-027**: `provider_products.model` column (admin-editable, no code change) + live capability probe of 2.5-flash / 2.5-pro on the production key → documented verdict |
| 4.1 | Quota-exhaustion auto-switch, capability routing, usage/switch logs | DONE (quota reservations, snapshots, pings timer, circuit breaker, failover audit `llm.failover`, per-product usage events) — keep |
| 5 | Step-by-step SE + DM execution, stage verification | milestones/tasks/stages with REVIEW→VERIFIED→DONE + UAT acceptance exist; AI writes 6 task profiles; human writes code/design | T-032 GitHub tooling (repo create, branch, commit generated code, CI status) extends automation without removing gates |
| 5.1/5.2 | GitHub/Codespaces as execution substrate | system itself lives on GitHub with full CI→deploy; project-level repo tooling absent | T-032 (VCSToken credential type already supported by T-027 schema) |
| 6 | Flexible service selection / combos across SE+DM | single-service `start_project_from_service`; catalog hierarchy 224 items | T-033 multi-service composition (plan = N service ids → merged blueprint) |
| 7 | Deliverables generation + managed execution | artifacts per task, project docs via AI profiles; image/audio/video gen absent | T-034 creative-tool credential types (image-gen etc.) once free tiers identified |
| 7.1 | Approval-checkpointed autonomous flow | task-level REVIEW gates + UAT + approvals page — matches brief steps 7-9 | keep; extend to new channels |
| 8 | Customer portal delivery incl. staging links | portal shows progress, artifacts, UAT; staging links per-project manual | T-035 portal artifact preview/staging links |
| 9 | Unified orchestration across all services | AI gateway + quota + benchmark governance = the kernel; channels/tools plug into it | this document is the integration contract |
| 10 | Overall behaviour | automation-first, human at designated gates — architecture already there | phases above |

## 2. T-027 scope (landed)

1. **Credential hub** (`app/modules/integrations`): tenant-scoped
   `integration_credentials` (type: LLM / EMAIL / MESSAGING / TRANSCRIPTION /
   VCS / GENERIC; Fernet-encrypted payload derived from SECRET_KEY; config
   JSONB; status DRAFT/ACTIVE/INACTIVE/FAILED; last-test result; audit on
   every mutation). `_provider_key` resolves DB-first, env fallback —
   env stays as disaster-recovery, not the primary store.
2. **Admin Integrations page** (`/admin/integrations`): create, edit,
   activate, deactivate, live-test (gemini/groq/openrouter model-list,
   telegram getMe, IMAP login), all through the UI — zero source changes.
3. **Unified intake** (`app/modules/intake`): channel-generic
   `intake_messages` (MANUAL now; EMAIL/TELEGRAM/WHATSAPP/VOICE slots) →
   governed AI classification (is this a project inquiry? domain? language?)
   → requirements extraction → Lead creation + admin notification, with the
   raw input, both AI outputs and the created lead stored verbatim on the
   record (brief §3 transparency). AI-unavailable ⇒ status NEEDS_REVIEW,
   fail-closed, no phantom leads.
4. **Model per product** (`provider_products.model`, admin-editable):
   switching gemini to a high-capability model becomes a DB edit. A live
   probe script tests candidate models on the real key and records the
   verdict in this doc.

## 3. Non-negotiables carried into every phase

- Fail-closed everywhere: unknown provider, stale quota, missing key ⇒
  PENDING_MANUAL, never silent degradation (SRS §14, docs/33).
- Every automated action is auditable and reversible; approvals gate
  anything client-facing (SRS HITL).
- Free-tier only while budget = 0 (docs/33); paid tiers enter as
  `is_paid` products with explicit founder opt-in.
- No credential ever rendered back to the browser in plaintext (UI shows
  a masked hint only).

## 4. "Why not high-capability Gemini?" — live probe verdict (2026-11-16)

Probed the production key against generativelanguage.googleapis.com:

- **gemini-2.5-flash / gemini-2.5-pro: RETIRED.** They still appear in the
  models list (26 entries match "2.5+"/"gemini-3"), but generateContent
  returns 404 "no longer available". No integration path exists.
- **gemini-3-flash-preview: REAL.** HTTP 200 in 1.2s on a live generation.
  But a 16-scenario benchmark run hit provider rate limits on 11/16
  (INCONCLUSIVE) — preview-tier free quota is too thin for a primary lane.
- Root cause of the original complaint was **hardcoded models** (T-024f
  fell back to gemma-4-26b-a4b-it after flash-line starvation and the id
  stayed in code). That is fixed structurally: `provider_products.model`
  is admin-editable, resolution = explicit arg > product.model > default.
- **Current policy (set live):** primary stays on the gemma-4 default (it
  carries the 57% conclusive benchmark evidence); gemini-3-flash-preview
  is recorded on the product as a verified alt (`alt_model_verified`) for
  admin switch-over when quota/quality justify a re-benchmark.

## 5. T-027 live verification (production, 2026-11-16)

1. Credential hub: gemini key stored (DRAFT) -> live test 200 -> **ACTIVE**
   -> `resolve_llm_key` returns the DB value (DB-first confirmed).
2. Model switch to gemini-3-flash-preview via DB edit (zero code) —
   confirmed the switch took effect end-to-end (the gate then correctly
   demanded fresh benchmark evidence — fail-closed works).
3. Intake live: real Malayalam-mixed WhatsApp message -> governed AI
   classification (SOFTWARE_ENGINEERING, lang=ml, openrouter) -> Lead
   created (source=WHATSAPP) -> founder Telegram notification enqueued.
   Requirements-extraction lane was provider-slow at that moment and
   fail-closed to empty — visible verbatim on the intake record.
4. Readiness smoke after deploy: 8/8 green.

## 6. Channel decisions (founder Q&A, 2026-11-16)

### Email — verdict: Gmail inbox + Cloudflare Email Routing (both managed)

Both options the founder named are supported and BOTH stay manageable:

- **Recommended receive path**: create the system Gmail account, then
  Cloudflare Email Routing (free) on aknja.pp.ua forwards
  requests@ / ops@ / contact@ (any alias, unlimited) into that ONE inbox.
  One IMAP poll point (T-028, live) ingests everything; the customer
  still writes to a branded address. Cloudflare routing is receive-only,
  so sending stays on Gmail SMTP (free ~500/day) — fine for ops replies.
- The poller is provider-independent: any IMAP host works by changing
  the credential config (Zoho free tier with true custom-domain
  mailboxes, or a self-hosted server later) — no code change.
- Automation: `aknja-email.timer` polls every 5 min; no-op until an
  ACTIVE EMAIL credential exists, so it is safe to enable already.
  First-poll guard: mail older than 7 days is marked seen and skipped.

### Telegram — verdict: existing bot CAN be reused; new bot recommended

Probed live: the current bot is @agent_os_2026_bot, webhook NONE (pure
outbound digest/approvals), 4 unread pending updates, group privacy ON.
- A Telegram bot is public by nature — anyone who finds @name can
  message it; with a webhook set, those messages reach our intake.
- Reusing @agent_os_2026_bot is NOT mandatory and NOT recommended: it is
  the founder's approval/digest channel; mixing public inbound into it
  blurs the trust boundary (a stranger's text would sit next to approval
  traffic). A second bot is free and takes 2 minutes at @BotFather
  ("newbot", copy the token, register it in Admin > Integrations with
  provider_key telegram_bot, Test, then run
  `python -m app.cli telegram-set-webhook`).
- T-029 webhook is live: verifies X-Telegram-Bot-Api-Secret-Token,
  deduplicates by update_id, ACKs in milliseconds before the AI runs.

### WhatsApp — verdict: manual intake now; WAHA/Cloud API deferred (T-030)

- **Cloud API (official)**: receiving user-initiated service
  conversations is free, BUT onboarding needs Meta business verification
  and a dedicated number — real friction for a solo founder.
- **WAHA (self-hosted, free)**: would dodge cost/verification but rides
  the unofficial WhatsApp Web channel — ban risk for the number, plus a
  gateway process to babysit on a 4 GB ARM box. Not worth it at current
  volume.
- **Decision**: WhatsApp stays on the manual intake path (already live —
  paste the message, channel=WHATSAPP, AI classification + lead + notify
  all work). Revisit Cloud API vs WAHA when inbound WhatsApp volume
  justifies it (docs/34 T-030).

## 7. T-028/T-029 scope (landed 2026-11-16)

- `integrations/email_poll.py`: IMAP UNSEEN -> header+body record ->
  intake pipeline (EMAIL channel) -> `\Seen` cursor; per-provider error
  isolation; injectable IMAP client for tests.
- `ui/hooks.py`: POST /hooks/telegram/{provider_key} — secret-token
  verification, update_id idempotency (intake_messages.external_id,
  unique index), persist-then-ACK ordering, non-text updates deferred
  until T-031, no 500s (no Telegram retry storms).
- CLI: `poll-email` (timer-safe no-op), `telegram-set-webhook`
  (generates + stores the webhook secret, calls setWebhook).
- infra: aknja-email.service/.timer (5 min), installed idempotently by
  the deploy script. Tests: 6 new (stub-IMAP pipeline incl. old-mail
  skip + provider failure isolation; webhook 404/403/ingest/dedupe/
  defer). Suite: 213 green.
