# Aknja Digital — Master SRS v6.1
**Document status:** Final consolidated development specification baseline  
**Version date:** 14 November 2026  
**Primary backend decision:** FastAPI (single backend)  
**Delivery model:** Staging-first; optional managed production hosting and post-production services.

## 1. Purpose
Aknja Digital is a solo-founder-operated digital services platform that coordinates business operations and delivery across software engineering, digital marketing, AI automation and support. It uses a Central AI Orchestrator with task-scoped specialist capabilities, deterministic tool enforcement, auditable project workflows and human authority.

## 2. Business and delivery boundary
Aknja is responsible by default for requirements discovery, estimation, implementation, QA, security checks, visual verification, bug fixing, staging deployment, client UAT and evidence-backed handover. Production hosting is optional: only when requested and commercially agreed. Aknja may deploy to client-owned infrastructure or offer Aknja-managed hosting subject to capacity and contract. Hosting, monitoring, backups, maintenance, support and enhancements have separate scopes/pricing.

## 3. Service catalog scope
The complete source taxonomy is preserved in `source_service_hierarchy.md`. It includes Software Engineering (10 top-level families) and Digital Marketing (9 top-level families), plus deliverables matrices. The catalog must support all source leaf services without claiming they are all immediately executable. Each service stores availability and execution readiness independently:
- Availability: `CATALOG_ONLY`, `AVAILABLE_MANUAL`, `AVAILABLE_WITH_PARTNER`, `AVAILABLE_AI_ASSISTED`, `AVAILABLE_AUTOMATED`, `SUSPENDED`.
- Readiness: `PLANNED`, `LIMITED`, `READY`, `SUSPENDED`, `RETIRED`.
A service can be sold only under a truthful availability mode, with prerequisites and exclusions disclosed.

## 4. Service hierarchy and execution contract
`Category → Subcategory → Service → Service Blueprint → Tasks → Deliverables → Package/Custom Plan`.
Every service blueprint defines: scope, exclusions, intake fields, prerequisites, feasibility checks, capability requirements, provider/tool requirements, data classification, workflow graph, execution mode, human approvals, QA checklist, deliverable contract, acceptance criteria, handover, warranty and maintenance options.

## 5. Core modules
1. Identity, authentication, roles and tenant isolation.
2. CRM, leads, qualification, discovery and client onboarding.
3. Service catalog, capability registry, packages, rates and custom quotes.
4. Proposal, contract, scope freeze and change requests.
5. Project, milestones, tasks, dependencies, artifacts and time/cost tracking.
6. Central AI Orchestrator, dynamic specialist worker runtime and memory retrieval.
7. Tool Gateway, approval service and immutable audit.
8. Resource registry, quota ledger, admission control, provider pools and compute scheduler.
9. Development workspaces, CI, QA, visual verification and test evidence.
10. Temporary reusable staging and client UAT portal.
11. Release artifact registry and optional production deployment manager.
12. Optional managed hosting, multi-project Docker Compose hosting and capacity manager.
13. Production monitoring, incident management, safe recovery and AI-assisted bug-fix workflow.
14. Backup, restore, disaster recovery and environment cleanup.
15. Billing, invoices, manual payment reconciliation, hosting subscriptions and support contracts.
16. Digital marketing workflows, analytics, content and campaign approval.
17. Notifications, durable email outbox, Telegram approval integration.
18. Reporting, observability, provider integrations and administration.

## 6. User roles
`SUPER_ADMIN`, `INTERNAL_OPERATOR` (founder default), `CLIENT_OWNER`, `CLIENT_MEMBER`, `PARTNER_OPERATOR`, `READ_ONLY_AUDITOR`, `SYSTEM_WORKER`. Enforce tenant-scoped authorization in the backend and database queries. UI hiding is not authorization.

## 7. AI operating model
One Central AI Orchestrator coordinates. Specialist capabilities are task-scoped and dynamically selected. Initial capability templates are defined in `.aknja/agents/README.md`. Workers have no independent privileged credentials. Tool Gateway validates actor, tenant, project, environment, scope, policy, quota, approval, idempotency and destination before executing.

## 8. Runtime and technical baseline
- Backend: FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic.
- Database: PostgreSQL; pgvector optional and derived.
- Frontend: HTML templates + HTMX + Alpine.js + Tailwind CSS; do not introduce a second backend.
- Jobs: database-backed durable job table initially; low concurrency; Redis optional cache only after quota validation.
- Browser QA: Playwright in isolated CI/staging runner, concurrency 1 initially.
- Containers: Docker + Docker Compose.
- CI: GitHub Actions; pin actions/dependencies/images.
- Storage: local dev filesystem; production S3-compatible adapter; private objects and short-lived signed URLs.
- Observability: structured logs, metrics, health endpoints, alerting and audit.
- No Kubernetes in initial release.

## 9. Environments
`local`, `ci`, `staging`, `production` must have separate configuration and secrets. Staging uses synthetic/test data. Production data must not be copied to staging without explicit authorization and anonymization. Temporary staging environments are reusable; their evidence and approved artifacts remain durable after environment cleanup.

## 10. Mandatory QA
Requirement traceability; unit/integration/contract/E2E tests; migration tests; lint/type checks; dependency/secret/container scans; UI reference comparison at fixed viewports; accessibility checks; performance smoke tests; security checks; regression; UAT. No milestone is accepted solely because code compiles or a container starts.

## 11. Release controls
Build once; deploy the same immutable artifact to staging and then production. Record commit SHA, image digest, SBOM, migration set, config version and test evidence. Production promotion requires explicit founder approval and client acceptance where contractually required. Use expand/contract DB migrations where possible. Rollback must be documented and tested.

## 12. Managed production hosting
Optional service. Each client application has a separate Compose project, network, secrets, persistent volume and database/user or dedicated DB. Reverse proxy routes hostnames. Enforce CPU/RAM/PID/storage limits and per-project health checks. Capacity admission uses measured load and reserve headroom; never promise a fixed application count from VM size alone. One VM is not HA. Client-owned hosting is preferred when workload or SLA exceeds Aknja capacity.

## 13. Production operations
Monitoring includes host and app health, CPU, memory, disk, TLS expiry, HTTP status, latency, DB health/connections, queue depth, backups, provider quotas and errors. AI may diagnose and create fix branches. Automatic actions are limited to allow-listed reversible recovery such as restarting an unhealthy stateless container or retrying an idempotent job. Code changes, migrations, data restore, DNS changes and production releases require approval.

## 14. Resource and zero-cost policy
Default `ZERO_COST_ONLY`, paid spend cap INR 0, no auto-upgrade, no auto-top-up, no paid fallback. Quota reservations are atomic. Unknown/stale quota is unavailable. Provider rotation must not evade limits. Candidate providers are not entitlements. Colab/Kaggle are opportunistic batch compute, not durable production hosting. Checkpoint long-running work and validate privacy/terms before uploading client data.

## 15. Commercial lifecycle
Lead → qualification → discovery → proposal → negotiation → signed contract → onboarding/assets → scope freeze → development → milestones → staging/UAT → acceptance → optional production hosting → warranty → maintenance/support/renewal → closure/archive. Manual payment recording/reconciliation is supported first; payment gateway is optional and requires approval.

## 16. Compliance and legal
India DPDP compliance workstream, consent, data minimization, retention/deletion, data subject requests, breach response and processor terms. GST/SAC/tax defaults in legacy source are placeholders requiring CA/legal review. Marketing messages require consent and platform policy compliance. No guaranteed SEO ranking, ad conversion or revenue. Package licenses and client IP transfer/reusable rights must be recorded.

## 17. Reporting
Lead funnel, project status, estimated vs actual effort/cost, profitability, capacity, hosting occupancy, service readiness, provider quota, AI quality, test evidence, incident trends, client satisfaction and delivery status. Never fabricate metrics; display source and freshness.

## 18. Definition of done
A requirement is done only when code, tests, security, documentation, staging deployment, verification evidence, approval and rollback strategy (where relevant) are present. See `docs/30_ACCEPTANCE_AND_DEFINITION_OF_DONE.md`.

## 19. Legacy baseline preservation
The complete v5.3 master baseline is appended below and preserved in a separate file. The detailed v5.3.1 Zero-Cost Guard and v5.3.2 provider pools/failover are preserved in separate source documents and remain mandatory. Where legacy assumptions conflict with v6.1, v6.1 amendments and ADRs govern; the original text is not silently rewritten.

---

# Preserved v5.3 Master SRS (verbatim source)
# Aknja Digital — Autonomous AI Freelance & Digital Agency OS
## Final Master Software Requirements Specification (SRS) & Architecture Blueprint

* **Document Version:** `v5.2` (v5.1 baseline preserved; implementation, delivery, multilingual voice, testing, staging and production documentation added)
* **Brand Name:** `Aknja Digital`
* **Legal & Billing Entity:** `Aknja Software Solutions` (Sole Proprietorship, MSME Udyam Registered — Poikkattussery, Aluva, Ernakulam, Kerala, India)
* **Primary Repository:** `aknja-digital` (Private Monorepo; `main` + `feat/*` / `fix/*` branches)
* **Public Domain:** `aknja.pp.ua` (Initial Staging/Launch) $\rightarrow$ `aknja.in` (Production Cutover via Admin Settings)
* **Build Scope:** Incremental delivery: local development → automated testing → staging → controlled production

---

## 1. Executive Summary, Architectural Vision & Zero-Hardcode Mandate

### 1.1 System Purpose & Solo-Founder Operating Model
**Aknja Digital** is an autonomous, zero-subscription software engineering, AI automation, and digital marketing platform governed by a single human founder acting as Super Admin. The platform enables one independent specialist to operate with the output capacity, quality assurance, and operational rigor of a full-stack digital agency while maintaining complete self-reliance and zero fixed monthly SaaS overhead.

### 1.2 Core Architectural Principles
1. **Zero-Hardcode Dynamic Configuration (New in v5.1):** No business rule, brand identity, domain name, email alias, payment milestone ratio, warranty duration, AI quota threshold, QA gate threshold, or HITL toggle may be hardcoded in application source code or AI prompt templates. All operational parameters are stored in PostgreSQL (`system_settings` and `infrastructure_runtime_profile`), cached in memory/Redis with instant invalidation on save, and editable via the multi-tab **Admin Settings UI (`/admin/settings`)**.
2. **Dual-Persona Execution Engine:** A single autonomous 26-agent orchestration layer serves clients under two configurable presentation personas (`solo_developer` vs. `agency_team`), selectable per lead, proposal, or project.
3. **Strict Zero-Subscription Baseline:** Built exclusively on always-free cloud tiers (Neon PostgreSQL, Cloudflare R2, Hugging Face Spaces, Oracle Cloud Always-Free ARM, Upstash Redis) paired with multi-provider free AI quota rotation.
4. **Human-in-the-Loop (HITL) Safety:** External client communications, bids, scope decompositions, ad launches, and production deployments pass through configurable Telegram inline approval gates.
5. **Tri-Tier Cross-Session Memory:**
   * *Declarative Memory (Single Source of Truth):* `docs/master_srs_v5.1.md` inside the repository.
   * *Semantic Memory:* Vector embeddings stored in Neon PostgreSQL (`pgvector`).
   * *Episodic Memory:* Structured handover logs in `memory/sessions/YYYY-MM-DD-session-N.md`.

---

## 2. Scope, Basis, Environment & Runtime Topology

### 2.1 Dual-Environment Deployment Strategy
The platform supports seamless switching between unified cloud staging and dedicated production hardware via the `infrastructure_runtime_profile` singleton table without code modifications:

| Parameter | Staging Profile (`UNIFIED_STAGING_HF_NEON`) | Production Profile (`PRODUCTION_OCI_12GB`) |
| :--- | :--- | :--- |
| **Compute Host** | Hugging Face Docker Space (16 GB RAM, 2 vCPU) | Oracle Cloud Always-Free ARM (12–24 GB RAM, 4 OCPU) |
| **Primary Database** | Neon PostgreSQL (Serverless + `pgvector` + Branching) | Neon PostgreSQL or Local PostgreSQL 16 + `pgvector` |
| **Object Storage** | Cloudflare R2 (`aknja-digital-artifacts`, 10 GB Free) | Cloudflare R2 (Zero-Egress S3-Compatible) |
| **Cache & Queue** | Upstash Serverless Redis / In-Process Memory | Local Redis 7 + Celery / ARQ Workers |
| **Local Heavy Tools** | `allow_local_openhands=FALSE`, `allow_local_playwright=FALSE`, `allow_self_hosted_n8n=FALSE` | `allow_local_openhands=TRUE`, `allow_local_playwright=TRUE`, `allow_self_hosted_n8n=TRUE` |
| **Active Domain** | `aknja.pp.ua` | `aknja.in` (Live switchable via `/admin/settings`) |

> **ERRATUM (2026-11-14) — staging compute host.** Hugging Face moved Docker
> and Gradio Spaces to paid plans (PRO/Team/Enterprise); only Static Spaces
> remain free (huggingface.co/docs/hub/en/spaces-overview). The
> `UNIFIED_STAGING_HF_NEON` staging host is therefore **no longer a
> zero-cost option** and is withdrawn from the free hosting pool
> (docs/34). Free staging now runs on the Oracle Cloud Always-Free ARM
> tenancy (same A1 baseline as production, a smaller shape) with Neon +
> Cloudflare R2 unchanged; Hugging Face remains in the pool only as a
> serverless inference candidate. The `infrastructure_runtime_profile`
> switching mechanism is unaffected.

### 2.2 Domain & Master Alias Propagation
When `public_domain` is updated in `system_settings` (e.g., from `aknja.pp.ua` to `aknja.in`), the system automatically updates:
* Client portal URLs, webhook callback URLs, and SEO canonical/sitemap links.
* Master agency email aliases (`ops@{domain}`, `projects@{domain}`, `leads@{domain}`, `billing@{domain}`).
* Generated PDF proposals, contracts, and invoice headers.

---

## 3. Governance, Dual-Persona Engine, Bilingual Bridge & HITL Gates

### 3.1 Dual-Persona Client Presentation Layer
* **`solo_developer` (Default for Freelance Platforms & Direct Founders):** Communicates in first-person singular (*"I have architected the API..."*, *"My automated test suite verified..."*), emphasizing direct founder accountability and speed.
* **`agency_team` (Enterprise & Turnkey Contracts):** Communicates as an organized engineering and growth studio (*"Our engineering unit has staged sprint build v1.2..."*, *"Our QA pipeline validated..."*).

### 3.2 Bilingual Bridge (Malayalam $\leftrightarrow$ Global Business English)
* **Inbound Founder Commands:** Malayalam text or voice notes sent via Telegram are transcribed (Whisper / Sarvam AI) and translated into structured English technical directives.
* **Client RFP & Ticket Digest:** Incoming English client briefs, messages, and bug reports are summarized into concise, actionable Malayalam digests pushed to the founder's Telegram chat.
* **Outbound Client Drafting:** Founder's Malayalam approval notes are synthesized into polished, culturally neutral global business English.
* **Bilingual Voice Synthesis:** Edge-TTS generates natural voiceovers for demos and reels using configurable `en-IN` and `ml-IN` neural voices.

### 3.3 Nine-Gate HITL Approval Matrix
Every high-impact action creates a record in `hitl_approvals` and dispatches an inline Telegram card (`Approve` / `Edit` / `Reject`). Each gate has an independent ON/OFF toggle in `system_settings` (allowing trusted low-risk workflows to be switched to auto-approve later):

1. `FREELANCE_PROPOSAL_SEND` — Outbound bid/cover letter submission.
2. `FREELANCE_CHAT_REPLY` — Pre-contract negotiation messages with leads.
3. `SCOPE_DECOMPOSITION` — Finalized SRS, milestone breakdown, and timeline sign-off.
4. `CHANGE_REQUEST_QUOTE` — Additional billing quotes triggered by post-signoff scope creep.
5. `WIREFRAME_DESIGN` — UI/UX prototype and design token approval before full sprint coding.
6. `CAMPAIGN_LAUNCH` — Transitioning ad campaigns or outbound outreach sequences out of `PAUSED` state.
7. `STAGING_DELIVERABLE` — Client-facing staging demo links and milestone handover packages.
8. `CLIENT_OUTBOUND_COMMS` — Formal status digests, delay notices, and invoice reminders.
9. `PRODUCTION_CUTOVER` — Final production deployment, DNS cutover, and repository transfer.

---

## 4. Freelance Marketplace Bridge & Lead Radar Engine

### 4.1 Multi-Channel Ingestion & Anti-Ban Compliance
* **Supported Channels:** `UPWORK`, `FIVERR`, `FREELANCER_COM`, `GURU_COM`, `CONTRA`, `REDDIT_FORHIRE`.
* **Anti-Ban Guard (`anti_ban_guard_locked = TRUE`):** Automated scrapers/feeds operate strictly in read-only ingestion mode using official RSS/APIs and rate-limited Jina Reader endpoints. Automated headless form-filling or bot-bidding against platform ToS is blocked at the architectural level; proposals are copied/dispatched only upon explicit founder approval.

### 4.2 Deterministic Lead Qualification & Scope Creep Detection
* **Feasibility Scoring (`0–100`):** Evaluates technical stack fit, budget realism, client payment verification, and clarity. Leads scoring $\ge$ `min_feasibility_score_threshold` (default `70`) trigger a Malayalam Telegram briefing.
* **Interview Likelihood Filter:** Prioritizes asynchronous, chat-closable projects when `preferred_interview_likelihood = LOW`.
* **Scope Creep Guard (`scope_creep_sensitivity = STRICT`):** Compares every new client message against the signed milestone scope; flags out-of-scope requests and automatically drafts a `CHANGE_REQUEST_QUOTE` for HITL approval.

---

## 5. Software Development Lifecycle (SDLC) & Quality Gates

### 5.1 Project State Machine
`LEAD_QUALIFIED` $\rightarrow$ `PROPOSAL_APPROVED` $\rightarrow$ `CONTRACT_SIGNED` $\rightarrow$ `ASSET_INTAKE` (or `BLOCKED_ON_CLIENT_KYC`) $\rightarrow$ `ARCHITECTURE_AND_WIREFRAME` $\rightarrow$ `DEVELOPMENT_SPRINT` $\rightarrow$ `QA_AND_SECURITY_GATE` $\rightarrow$ `STAGING_UAT` $\rightarrow$ `PRODUCTION_HANDOFF` $\rightarrow$ `WARRANTY_AND_AMC`.

### 5.2 Intake & Wireframe Modes
* **Asset Intake Mode (`default_asset_intake_mode`):**
  * `CLIENT_PROVIDED`: Waits for client logos, brand colors, and copy, sending automated reminders every `client_kyc_reminder_interval_hours` (default `24h`).
  * `ZERO_ASSET_STARTUP` (Default): Autonomously generates SVG logos, color palettes, typography, and placeholder copy so sprint execution never stalls.
* **Wireframe Mode (`default_wireframe_mode`):**
  * `STANDARD_TEMPLATE` (Default): Rapid responsive UI assembly using Tailwind CSS + daisyUI.
  * `CUSTOM_UI`: Bespoke design tokens and custom component architecture.

### 5.3 Mandatory Automated QA & Security Gates
No pull request or milestone build may advance to `STAGING_UAT` unless all configured gates pass:
* **Unit & Integration Coverage:** PyTest coverage $\ge$ `min_pytest_coverage_pct` (default `80%`).
* **AI Critic Code Review:** Automated architectural & edge-case review score $\ge$ `min_critic_ai_score` (default `85/100`).
* **Static Linting:** `ruff check` must return zero errors when `enforce_ruff_zero_errors = TRUE`.
* **E2E Browser Verification:** Headless Playwright functional flows pass with zero console/network exceptions.
* **Security & Secret Scan:** OWASP Top-10 checks and regex/entropy secret scanning verify zero leaked tokens in Git.
* **Docs Sync Gate:** When `enforce_docs_sync_gate = TRUE`, feature PRs modifying APIs or schemas must include corresponding `docs/` updates.

---

## 6. Digital Marketing Lifecycle (DMLC), GEO/SEO & Omnichannel Engine

1. **Technical SEO & Generative Engine Optimization (GEO):** Automated generation of `llms.txt`, structured JSON-LD schemas, semantic HTML, XML sitemaps, and 95+ Core Web Vitals performance budgets.
2. **Creative Vector & Motion Studio:** Programmatic SVG brand kits, social media carousels, and automated short-form promotional videos rendered via Remotion + FFmpeg with bilingual Edge-TTS narration.
3. **Omnichannel Publishing & Lifecycle Automation:** Scheduled social publishing (Postiz/Mixpost connectors), transactional email drips, and WhatsApp Business workflows (WAHA / Evolution API) governed by `whatsapp_daily_warmup_limit` (default `50` messages/day) to protect number reputation.
4. **Performance Marketing Governance:** Google and Meta ad campaign structures and conversion tracking scripts are generated strictly in `PAUSED` state and require `CAMPAIGN_LAUNCH` HITL approval. Creative A/B variants are evaluated over `dmlc_ab_evaluation_window_days` (default `5` days).

---

## 7. Four-Layer Zero-Cost AI Compute & Quota Failover Scheduler

### 7.1 Provider Hierarchy
1. **Layer 1 — Free Cloud LLM APIs (Primary):** Rotating free API keys across Google AI Studio (Gemini 2.5 Pro/Flash), Groq Cloud (Llama-3.3-70B, Qwen-Coder), Cerebras, OpenRouter (`:free` models), Mistral, and Hugging Face Serverless.
2. **Layer 2 — Persistent Web-UI Bridge:** Playwright + Camoufox fingerprint-shielded sessions for extended reasoning when API tiers hit daily caps.
3. **Layer 3 — Self-Hosted Local AI (OCI ARM):** Ollama running `qwen2.5-coder:7b` and `llama3.2:3b` for offline resilience and zero-cost background tasks.
4. **Layer 4 — Ephemeral Cloud GPU / Batch Offload:** Heavy media rendering, TTS batching, and ML tasks offloaded to Hugging Face Spaces, Modal.com free credits, or Kaggle Notebooks, saving checkpoints every `gpu_checkpoint_interval_min` (default `10` minutes) to Cloudflare R2.

### 7.2 Routing & Circuit-Breaker Rules
* **Strict Free-First Policy (`exhaust_free_first_strict_mode = TRUE`):** Paid adapters are never invoked while any free-tier pool has remaining capacity.
* **Pre-Flight Soft Switch (`soft_switch_threshold_pct = 85.00%`):** When a provider key reaches $85\%$ of its daily quota, new requests proactively route to the next healthy key/provider.
* **Sub-15ms Circuit Breaker:** Any `HTTP 429` (Rate Limit), `HTTP 402` (Quota/Billing), or `HTTP 5xx` response trips the provider circuit immediately, retrying up to `default_max_retries` (`3`) across fallback layers and cooling down for `quota_resume_buffer_sec` (`30s`).

---

## 8. Centralized System-Wide Configuration Architecture, Schema & Legal Compliance

### 8.1 Zero-Hardcode `system_settings` Engine
All business, operational, and technical defaults live in a typed PostgreSQL `system_settings` table exposed via `/api/v1/admin/settings` and a multi-tab **Admin Settings UI (`/admin/settings`)**. Saving any setting validates types, writes an immutable entry to `audit_logs`, invalidates the Redis/in-memory cache immediately, and propagates updated values across all active services, generators, and AI prompt builders.

### 8.2 Complete 8-Domain Configuration Matrix (Seeded Defaults)

#### Tab 1: Brand, Domain & Agency Master Identities
| Setting Key | Seeded Default Value | Data Type | Propagation Scope |
| :--- | :--- | :--- | :--- |
| `brand_name` | `Aknja Digital` | `string` | UI headers, portals, proposals, emails, AI system prompts |
| `legal_billing_name` | `Aknja Software Solutions` | `string` | PDF invoices, contracts, tax declarations |
| `public_domain` | `aknja.pp.ua` (switchable to `aknja.in`) | `string` | Portal URLs, webhooks, SEO canonicals, email aliases |
| `agency_master_aliases` | `{"ops":"ops@aknja.pp.ua","projects":"projects@aknja.pp.ua","leads":"leads@aknja.pp.ua","billing":"billing@aknja.pp.ua"}` | `jsonb` | Auto-regenerates on `public_domain` change unless overridden |
| `brand_logo_r2_key` | `branding/aknja-digital-logo.svg` | `string` | Client portal, PDF invoices, proposals |
| `business_address` | `Poikkattussery, Aluva, Ernakulam, Kerala, India` | `text` | Invoices, contracts, legal footers |
| `udyam_reg_number` | `KL02D0023222` (updatable to `UDYAM-KL-02-XXXXXXX`) | `string` | Invoices, MSME verification blocks |
| `tax_pan_number` | `""` (Configurable in Admin UI) | `string` | Indian client invoices & payment gateway KYC |
| `default_admin_language` | `ml` (`ml` \| `en`) | `enum` | Telegram digest language & Admin UI default locale |

#### Tab 2: Commercial, Contract, Invoicing & Tax Defaults
| Setting Key | Seeded Default Value | Data Type | Propagation Scope |
| :--- | :--- | :--- | :--- |
| `warranty_days` | `30` | `integer` | Proposals, contracts, post-handoff warranty timers |
| `payment_milestone_split` | `[30, 30, 40]` | `jsonb` | Auto-generates 3 milestone invoices (Advance / Staging UAT / Final) |
| `quote_validity_days` | `15` | `integer` | Proposal & quotation expiry calculation |
| `free_revision_rounds` | `2` | `integer` | Contract terms & scope-creep guard baseline |
| `primary_domestic_currency` | `INR` | `string` | Domestic billing (stored internally in Paise minor units) |
| `international_marketplace_currency` | `USD` | `string` | International billing (stored internally in Cents minor units) |
| `auto_fx_rate_sync` | `true` | `boolean` | Daily USD $\leftrightarrow$ INR conversion sync for revenue telemetry |
| `tax_mode` | `NON_GST_EXEMPT` (`NON_GST_EXEMPT` \| `GST_REGISTERED`) | `enum` | Prints Section 22 CGST exemption note until GSTIN is enabled |
| `gstin_number` | `""` | `string` | Activated automatically when `tax_mode = GST_REGISTERED` |
| `default_sac_code` | `998314` | `string` | IT design and development services SAC code on invoices |
| `invoice_prefix` | `AKN-2026-` | `string` | Sequential invoice numbering (`AKN-2026-0001`, etc.) |
| `payment_bank_upi_details` | `{"bank_name":"","account_name":"Aknja Software Solutions","account_no":"","ifsc":"","upi_id":"","wise_handle":""}` | `jsonb` | Rendered dynamically on generated PDF invoices & payment links |

#### Tab 3: AI Scheduler, Failover & Quota Controls
| Setting Key | Seeded Default Value | Data Type | Propagation Scope |
| :--- | :--- | :--- | :--- |
| `soft_switch_threshold_pct` | `85.00` | `numeric` | Pre-flight router proactive key rotation threshold |
| `gpu_checkpoint_interval_min` | `10` | `integer` | Layer 4 Kaggle/Colab/Modal R2 state snapshot interval |
| `default_max_retries` | `3` | `integer` | Cross-layer retry count before task quarantine |
| `quota_resume_buffer_sec` | `30` | `integer` | Cooldown window after HTTP 429/5xx circuit trip |
| `exhaust_free_first_strict_mode` | `true` | `boolean` | Enforces 100% free-pool utilization before paid adapters |

#### Tab 4: Automated QA Gates & Self-Evolution Safety
| Setting Key | Seeded Default Value | Data Type | Propagation Scope |
| :--- | :--- | :--- | :--- |
| `min_pytest_coverage_pct` | `80` | `integer` | CI/CD & PR merge gate minimum test coverage |
| `min_critic_ai_score` | `85` | `integer` | Minimum AI Critic review score (`0–100`) to pass QA gate |
| `enforce_ruff_zero_errors` | `true` | `boolean` | Blocks PRs with Python lint/formatting violations |
| `enforce_docs_sync_gate` | `true` | `boolean` | Enforces `docs/` updates on schema/API feature branches |
| `self_evolution_healthz_rollback_sec` | `15` | `integer` | Auto-rollback timeout if `/healthz` fails after self-update |

#### Tab 5: HITL Approval Gates & Bilingual Voice Settings
| Setting Key | Seeded Default Value | Data Type | Propagation Scope |
| :--- | :--- | :--- | :--- |
| `hitl_gate_overrides` | `{"FREELANCE_PROPOSAL_SEND":true,"FREELANCE_CHAT_REPLY":true,"SCOPE_DECOMPOSITION":true,"CHANGE_REQUEST_QUOTE":true,"WIREFRAME_DESIGN":true,"CAMPAIGN_LAUNCH":true,"STAGING_DELIVERABLE":true,"CLIENT_OUTBOUND_COMMS":true,"PRODUCTION_CUTOVER":true}` | `jsonb` | Per-gate ON/OFF toggle for Telegram approval vs. auto-approve |
| `tts_voice_en` | `en-IN-NeerjaNeural` | `string` | Default English Edge-TTS neural voice |
| `tts_voice_ml` | `ml-IN-SobhanaNeural` | `string` | Default Malayalam Edge-TTS neural voice |

#### Tab 6: Freelance Marketplace Bridge Rules
| Setting Key | Seeded Default Value | Data Type | Propagation Scope |
| :--- | :--- | :--- | :--- |
| `min_feasibility_score_threshold` | `70` | `integer` | Minimum score (`0–100`) to notify founder & draft bid |
| `preferred_interview_likelihood` | `LOW` (`LOW` \| `MEDIUM` \| `ANY`) | `enum` | Lead radar ranking filter for async-friendly jobs |
| `scope_creep_sensitivity` | `STRICT` (`STRICT` \| `BALANCED` \| `FLEXIBLE`) | `enum` | Sensitivity of post-contract scope-creep detector |
| `enabled_marketplaces` | `["UPWORK","FIVERR","FREELANCER_COM","GURU_COM","CONTRA","REDDIT_FORHIRE"]` | `jsonb` | Active ingestion adapters in Lead Radar |
| `anti_ban_guard_locked` | `true` | `boolean` | Locks read-only ingestion compliance across marketplace bridges |

#### Tab 7: SDLC & DMLC Default Modes & Timers
| Setting Key | Seeded Default Value | Data Type | Propagation Scope |
| :--- | :--- | :--- | :--- |
| `default_asset_intake_mode` | `ZERO_ASSET_STARTUP` (`ZERO_ASSET_STARTUP` \| `CLIENT_PROVIDED`) | `enum` | Controls autonomous brand asset generation vs. KYC wait |
| `default_wireframe_mode` | `STANDARD_TEMPLATE` (`STANDARD_TEMPLATE` \| `CUSTOM_UI`) | `enum` | Default UI prototyping strategy |
| `client_kyc_reminder_interval_hours` | `24` | `integer` | Reminder cadence for `BLOCKED_ON_CLIENT_KYC` projects |
| `dmlc_ab_evaluation_window_days` | `5` | `integer` | Ad creative A/B test evaluation duration |
| `whatsapp_daily_warmup_limit` | `50` | `integer` | Max daily outbound WhatsApp messages via WAHA/Evolution |

#### Tab 8: Infrastructure Runtime Profile (`infrastructure_runtime_profile` Singleton)
Exposes the `infrastructure_runtime_profile` singleton directly inside `/admin/settings` so switching from `UNIFIED_STAGING_HF_NEON` (`aknja.pp.ua`) to `PRODUCTION_OCI_12GB` (`aknja.in`) updates `active_profile`, `total_ram_mb`, `public_domain`, and local service toggles (`allow_local_openhands`, `allow_local_playwright`, `allow_self_hosted_n8n`) in one click.

### 8.3 Core PostgreSQL Database Schema Overview
* `system_settings`: `key (PK)`, `category`, `value_json (JSONB)`, `value_type`, `description`, `is_sensitive`, `updated_by`, `updated_at`.
* `infrastructure_runtime_profile`: `id (PK=1)`, `active_profile`, `public_domain`, `total_ram_mb`, `allow_local_openhands`, `allow_local_playwright`, `allow_self_hosted_n8n`, `updated_at`.
* `clients` & `projects`: Tracks persona (`solo_developer` | `agency_team`), SDLC state, intake mode, warranty expiry date, and R2 artifact prefixes.
* `milestones` & `invoices`: Stores minor-unit amounts (`amount_minor`, `currency`), milestone percentages synced from `payment_milestone_split`, SAC `998314`, Non-GST/GST tax metadata, and PDF R2 keys.
* `hitl_approvals`: Stores gate type, payload snapshot, Malayalam summary, Telegram message ID, status (`PENDING` | `APPROVED` | `REJECTED` | `AUTO_APPROVED`), and decision timestamp.
* `freelance_leads`: Stores marketplace source, external URL hash, feasibility score, interview likelihood, and drafted proposal.
* `ai_provider_quotas`: Real-time token/request counters, soft-switch states, and circuit-breaker cooldown timestamps.
* `audit_logs`: Immutable log of all settings mutations, HITL approvals, invoice generations, and self-evolution deployments.

### 8.4 India / Kerala Solo Proprietorship Compliance
* **Home-Based Operation:** Operated legally from the founder's residence in Aluva, Ernakulam, Kerala under MSME Udyam (`Aknja Software Solutions`, NIC `62011`, `62013`, `62020`, `62099`).
* **Taxation:** Operates under GST Section 22 exemption (`NON_GST_EXEMPT`) below the ₹20 Lakh turnover threshold with one-click GSTIN activation in Tab 2 when crossed; Income Tax structured for Section 44ADA presumptive taxation.

---

## 9. Self-Evolution (`aknja-digital`), Documentation Runbooks & `.env` Secrets Contract

### 9.1 Self-Evolution Workflow (`is_self_system = TRUE`)
Internal improvements to `aknja-digital` execute on isolated `feat/*` or `fix/*` branches, pass all Tab 4 QA gates, require `PRODUCTION_CUTOVER` HITL sign-off, and monitor `/healthz` for `self_evolution_healthz_rollback_sec` (`15s`) post-deploy—automatically reverting to the previous container image on health failure.

### 9.2 Required `docs/` Deliverables
The repository must include comprehensive Markdown runbooks inside `docs/`:
1. `docs/telegram-bot-setup.md` — Step-by-step guide to creating the dedicated **Aknja Digital** bot via `@BotFather`, generating `TELEGRAM_BOT_TOKEN`, retrieving `TELEGRAM_ADMIN_CHAT_ID` via `@userinfobot` / `getUpdates`, and configuring webhook/polling modes securely.
2. `docs/domain-migration.md` — Checklist for migrating DNS on Cloudflare and switching `public_domain` from `aknja.pp.ua` to `aknja.in` in `/admin/settings`.
3. `docs/deployment-staging-to-oci.md` — Guide for deploying on Hugging Face Spaces + Neon + R2 and promoting to Oracle Cloud ARM (12–24 GB RAM).

### 9.3 Secrets-Only `.env.example` Contract
Non-secret configuration belongs strictly in `system_settings`. Only cryptographic secrets and connection URIs belong in `.env`:

```ini
# ==============================================================================
# AKNJA DIGITAL — SECRETS & INFRASTRUCTURE URIS (.env)
# ==============================================================================
APP_ENV=staging
SECRET_KEY=change-me-to-a-64-char-random-hex-string
ADMIN_PASSWORD_HASH=change-me-bcrypt-hash

# Database & Cache
DATABASE_URL=postgresql+asyncpg://user:pass@ep-xxx.neon.tech/aknja_digital?sslmode=require
REDIS_URL=rediss://default:token@xxx.upstash.io:6379

# Cloudflare R2 Object Storage
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=aknja-digital-artifacts

# Telegram HITL Control Plane (Aknja Digital Bot)
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_ID=

# Layer 1 Free AI Provider Pool
GEMINI_API_KEYS=key1,key2
GROQ_API_KEYS=key1,key2
CEREBRAS_API_KEY=
OPENROUTER_API_KEY=
MISTRAL_API_KEY=
HF_TOKEN=

# Optional Compute Offload & Integrations
MODAL_TOKEN_ID=
MODAL_TOKEN_SECRET=
KAGGLE_USERNAME=
KAGGLE_KEY=
JINA_API_KEY=
WAHA_API_URL=
WAHA_API_KEY=
```

---

## 10. Single-Stage Build Specification & Acceptance Criteria (`P0`–`P2`)

### 10.1 Priority `P0` — Core Foundation, Dynamic Settings & HITL Control Plane
* FastAPI async backend + PostgreSQL (`SQLAlchemy` + `Alembic` migrations + `pgvector`) + responsive Admin Dashboard (HTMX/Alpine.js or React + Tailwind CSS + daisyUI).
* **Centralized `system_settings` Service & `/admin/settings` 8-Tab UI:** Full CRUD, type validation, cache invalidation on save, and seeded defaults matching Section 8.2.
* **Telegram Bot & 9-Gate HITL Engine:** Async bot worker (`aiogram` / `python-telegram-bot`) delivering Malayalam summaries with inline `Approve` / `Edit` / `Reject` callbacks, respecting per-gate overrides in Tab 5.
* **Cloudflare R2 Storage Adapter:** Upload/download/signed-URL service for logos, invoices, proposals, and GPU checkpoints.

### 10.2 Priority `P1` — SDLC Orchestrator, Freelance Bridge & Dynamic Billing Engine
* **Lead Radar & Proposal Generator:** Marketplace ingestion pipeline, deterministic feasibility scorer (`Tab 6`), bilingual Malayalam briefing, and persona-aware (`solo_developer` vs. `agency_team`) proposal generator reading warranty/milestone rules from `Tab 2`.
* **SDLC Project Tracker & Client Portal:** Client-facing portal hosted under active `public_domain` (`aknja.pp.ua` $\rightarrow$ `aknja.in`) showing milestone progress, staging previews, and asset upload.
* **Dynamic Invoicing & Contract PDF Engine:** Generates INR/USD PDF invoices and contracts pulling `legal_billing_name` (`Aknja Software Solutions`), Udyam/PAN, `tax_mode` (`NON_GST_EXEMPT`), SAC `998314`, `payment_milestone_split` (`30/30/40`), `warranty_days` (`30`), and bank/UPI details live from `Tab 1` & `Tab 2`.
* **4-Layer AI Quota & Failover Router:** Pre-flight quota tracker (`85%` soft switch), circuit breaker (`<15ms`), and fallback chain across Layer 1–4 (`Tab 3`).

### 10.3 Priority `P2` — DMLC Studio, Bilingual Voice, Self-Evolution & Telemetry
* **DMLC & GEO Content Studio:** Programmatic SEO/`llms.txt` generator, SVG/Remotion media pipeline, Edge-TTS bilingual audio (`en-IN` / `ml-IN` from `Tab 5`), and `PAUSED`-by-default ad campaign builder (`Tab 7`).
* **QA Gate & Self-Evolution Runner:** Automated PyTest/Ruff/Critic AI gate runner (`Tab 4`) and `/healthz` rollback watchdog.
* **Executive Telemetry & Runbooks:** Unified dashboard for MRR/revenue (INR & USD), AI free-tier quota utilization, active leads, and complete `docs/` setup guides (`docs/telegram-bot-setup.md`, `docs/domain-migration.md`, `docs/deployment-staging-to-oci.md`).

---

# 11. Version 5.2 Additions — Delivery Engineering & Operational Documentation

## 11.1 Document status and interpretation
This version preserves the v5.1 requirements and adds the implementation and operational controls below. Values that depend on provider plans, free quotas, account eligibility, OCI region capacity, or legal/tax status are **configuration candidates**, not guarantees. Verify them in the actual provider console before enabling a service. No external API key, password, token, private key, client secret, or production data may be committed to Git.

## 11.2 Delivery lifecycle
The mandatory delivery path is:
`BACKLOG → SPECIFIED → IMPLEMENTING → CODE_REVIEW → AUTOMATED_TESTS → SECURITY_REVIEW → STAGING_DEPLOYED → STAGING_VERIFIED → HUMAN_ACCEPTANCE → RELEASE_APPROVED → PRODUCTION_DEPLOYED → POST_DEPLOY_VERIFIED`.

A feature is not complete merely because code was written or a container starts. Each feature must have:
- linked requirement and GitHub issue;
- implementation branch and reviewed pull request;
- migration and rollback strategy where data changes;
- unit, integration and applicable end-to-end tests;
- security and dependency checks;
- updated user/developer/runbook documentation;
- staging deployment evidence and test report;
- explicit acceptance criteria and owner sign-off;
- production release note and rollback plan where applicable.

## 11.3 Multilingual Communication & Voice Engine
A centralized service shall support configurable languages and per-user preferences. Initial target languages: Malayalam (`ml`), English (`en`), Hindi (`hi`) and Tamil (`ta`). The language registry must allow future additions without code changes.

Required capabilities:
- user input language, preferred display language, preferred spoken response language, voice and auto-translation preferences;
- source text/audio reference retained separately from translated text;
- message-level `original_language`, `target_language`, `provider`, `model`, `translation_status`, `created_at`, `quality_flag` and user correction;
- auto-translate and manual translate controls;
- glossary/terminology preservation for technical, legal, financial and product terms;
- speech-to-text, text translation, text-to-speech and optional streaming speech-to-speech;
- voice consent, recording indicator, retention policy, deletion workflow and provider disclosure;
- translation confidence/uncertainty indicator; users can view original content at all times;
- provider adapters for Gemini Live/API, Microsoft Azure AI Speech, Sarvam AI, Whisper-compatible STT, Edge-TTS and optional self-hosted translation;
- provider fallback must respect provider terms, privacy, rate limits and budget caps. Multiple keys must not be rotated to evade a provider's quota or account restrictions.

Gemini Live is an optional real-time conversational adapter, not a mandatory dependency. Use ephemeral/client-side credentials where supported; otherwise proxy through the backend with strict session authorization and short-lived tokens. Never expose long-lived API keys in browser JavaScript.

## 11.4 Additional data model
Add and migrate the following entities:
- `supported_languages`
- `user_language_preferences`
- `translation_provider_configs` (references secret names; never stores raw secrets)
- `speech_provider_configs` (references secret names)
- `messages`
- `message_translations`
- `voice_sessions`
- `voice_transcriptions`
- `voice_assets` (object-storage key, duration, codec, consent, retention expiry; no public object URLs)
- `translation_glossary_terms`
- `provider_usage_events`
- `release_records`
- `test_runs` and `test_evidence`

Original messages must be immutable except for explicit edit/version records. Translations are derived records and may be regenerated. Do not overwrite original content with translated content.

## 11.5 Environment separation
- `local`: developer workstation; synthetic data; local `.env`.
- `ci`: disposable test database and mock external providers; no production secrets.
- `staging`: staging domain, separate database/project or isolated schema, test accounts and synthetic client data.
- `production`: production domain, production secrets, restricted admin access, backups and monitoring.

Never copy production client records into local or staging unless explicitly authorized and safely anonymized. A staging release must not silently change production DNS or production data.

## 11.6 Deployment topology for the currently described OCI allocation
The currently described allocation is two OCI Ampere A1 VMs, each 1 OCPU and 6 GB RAM. Together they consume the published Always Free A1 allowance of 2 OCPUs and 12 GB RAM. Treat these two VMs as the current capacity; do not plan on an additional A1 VM without a verified account quota change.

Proposed initial roles:
- `oci-app-01` (1 OCPU / 6 GB): Nginx + FastAPI application + lightweight frontend/API containers. Keep PostgreSQL on Neon initially to avoid memory pressure.
- `oci-worker-01` (1 OCPU / 6 GB): Celery/ARQ workers, scheduled jobs, webhook consumers, QA jobs with strict concurrency limits. Do not run a large local LLM or OpenHands alongside all workers.
- Neon: managed PostgreSQL for initial staging/early production, with verified backups and export/restore drills.
- Cloudflare R2: client deliverables and encrypted backup artifacts; do not use as the only backup of the database.
- Redis: begin with a managed free/low-resource option only after checking current limits; otherwise use a small local Redis on the worker host. Keep queue durability and retry policy explicit.
- GitHub Actions: CI; self-hosted runner only if necessary and isolated from production credentials.

Staging and production may share the two VMs only with explicit resource budgets and isolation. Prefer staging on worker host or a separate compose project and production on app host after acceptance. Do not claim high availability: two small VMs in one tenancy/region are not a complete HA design.

## 11.7 Build priorities
- P0: repository, local dev, CI, authentication, dynamic settings, audit logs, secrets handling, migrations, backup/restore baseline, basic admin UI and HITL.
- P1: clients/projects/requirements, GitHub workflow, AI provider abstraction, project lifecycle, client portal, document generation, test reporting.
- P2: multilingual text chat, translation records, voice transcription/TTS, marketing workflows, telemetry.
- P3: real-time voice/voice-to-voice translation, advanced agent tools, external marketplace adapters, production hardening and scale.
P3 is an explicit extension of v5.1's P0–P2 plan, not a replacement.

## 11.8 Non-negotiable safety controls
- Production deploy, DNS cutover, client-facing proposal/message, paid campaign, financial action, destructive database operation and repository transfer require HITL approval.
- API keys are scoped, rotated on compromise, stored in environment secrets/secret manager, masked in logs and never sent to AI prompts.
- External AI requests are data-classified. Confidential client data is blocked from providers unless the client contract, provider terms and configured consent allow it.
- Quota fallback may switch providers only within terms and privacy rules. Do not create accounts or rotate keys to bypass limits.
- Backups must be encrypted, access-controlled, periodically restored in a test environment and have documented RPO/RTO targets.
- Production migrations use expand/contract where possible; destructive migrations require backup and explicit approval.

## 11.9 Acceptance criteria for v5.2
The system is ready for first controlled production use only when:
1. Local, CI and staging configurations are separate and reproducible.
2. A new developer can follow the setup guides from a clean machine.
3. CI blocks merge on failing tests, lint, secret scanning and required documentation.
4. A release can be deployed to staging and rolled back using documented commands.
5. Database backup and restore have been demonstrated.
6. Admin and client authorization tests prove tenant isolation.
7. Original and translated messages are both preserved and viewable.
8. Speech features have consent, failure fallback, language selection and quota/cost controls.
9. No secret appears in Git history, build logs, browser bundles or client-facing artifacts.
10. Production release requires a recorded human approval and post-deploy health check.

## 11.10 Provider and infrastructure assumptions requiring live verification
The v5.1 references to Hugging Face Docker Spaces as a free compute baseline, OCI 12–24 GB/4 OCPU production hardware, and permanently free rotating API pools must not be treated as guarantees. Verify current plan eligibility, quota, pricing, region, terms and account-specific capacity. The current OCI A1 allocation described by the owner is 2 OCPU/12 GB total. Hugging Face currently distinguishes free static Spaces from compute-backed Docker/Gradio Spaces, which may require a paid subscription on CPU Basic. Neon, Cloudflare R2, Gemini, Azure Speech and Sarvam free credits/quotas are limited and subject to change.

---

# 12. Developer Documentation Package
The companion documents in `docs/` define the practical setup and delivery process:
- `DEVELOPMENT_HANDBOOK.md`
- `ENVIRONMENT_AND_SECRETS_SETUP.md`
- `PROVIDER_ACCOUNT_AND_API_KEY_SETUP.md`
- `OCI_INSTANCE_AND_NETWORK_SETUP.md`
- `TESTING_AND_QA_RUNBOOK.md`
- `STAGING_DEPLOYMENT_RUNBOOK.md`
- `PRODUCTION_DEPLOYMENT_RUNBOOK.md`
- `OPERATIONS_BACKUP_SECURITY_RUNBOOK.md`
- `FEATURE_COMPLETION_CHECKLIST.md`

These guides are intended to be committed into the private `aknja-digital` repository and updated with each implementation change.




---

# Version 5.3 — Verified Infrastructure & Implementation Addendum

**This addendum supersedes conflicting infrastructure, hosting and release assumptions in the preserved v5.2 baseline. All other v5.2 product requirements, configuration matrices, SDLC/DMLC requirements, billing placeholders, HITL gates and module scope remain part of the baseline unless explicitly amended below.**

## A. Corrections to previous hosting assumptions

1. The previous `UNIFIED_STAGING_HF_NEON` profile must not assume a free 16 GB / 2 vCPU Docker runtime on Hugging Face. Current official Spaces documentation says compute-backed Docker/Gradio Spaces require a paid plan; Static Spaces are free. Remove Docker Spaces from the free hosting baseline.
2. The previous `PRODUCTION_OCI_12GB` table's 4 OCPU / 24 GB A1 assumption is not the known Always Free allocation. OCI currently documents 2 OCPU / 12 GB total for Always Free A1.
3. The two known 1 OCPU / 6 GB A1 VMs consume the A1 compute allowance if confirmed in the tenancy. Do not allocate additional A1 compute unless the tenancy's quota and billing page confirms it.
4. OCI currently documents 200 GB total Always Free block-volume storage, including boot volumes. Measure existing boot volumes before adding E2.1.Micro VMs.
5. Render Free is not the durable staging baseline: free web services sleep after 15 minutes idle, have ephemeral local filesystems and may restart.
6. GCP e2-micro Always Free is limited to selected US regions and a small monthly egress allowance. It is not a reliable India-region app host.
7. Free API quotas are not interchangeable with production SLAs. A provider can change model access, limits, eligibility, data terms or pricing.

## B. Approved practical environment topology

- Developer workstation: local development, unit tests, migrations and browser tests.
- OCI VM-A (1 OCPU / 6 GB): protected staging environment.
- OCI VM-B (1 OCPU / 6 GB): production environment after staging acceptance.
- Optional OCI E2.1.Micro: monitoring/bastion/lightweight utility only, if tenancy quota and shared disk allocation permit.
- GitHub: source control, issues, PRs, CI and immutable release records.
- Neon: development/staging DB during initial build, subject to current quota and export/backup checks.
- Cloudflare R2: private file/object storage, subject to free-tier request/storage limits.
- Upstash Redis: optional cache/queue only after command/bandwidth quota validation.
- AI and speech providers: optional adapters, not mandatory runtime dependencies.

Do not run all services on a single 6 GB VM. In particular, avoid local LLM inference, OpenHands, browser fleets, Playwright concurrency, PostgreSQL, Redis and multiple workers together. Use a modular monolith and low-concurrency worker model.

## C. Staging must not be skipped

A staging environment is mandatory for the initial production release. It may be hosted on VM-A and accessed through:
- restricted IP + Nginx basic authentication or VPN;
- a temporary hostname; or
- a controlled subdomain.

A public production domain is not required for most functional tests. Final HTTPS, secure-cookie, OAuth callback and webhook tests must use a valid hostname before launch. Do not disable security controls to accommodate IP-only testing.

## D. Release state machine

`LOCAL → CI → STAGING_DEPLOYED → SMOKE_TESTED → UAT_ACCEPTED → BACKUP_VERIFIED → RELEASE_APPROVED → PRODUCTION_DEPLOYED → POST_DEPLOY_VERIFIED`

Any failed gate returns the release to `BLOCKED`; production is not changed. Production cutover requires a founder approval record tied to the exact commit SHA and image digest.

## E. AI agent count correction

The “26-agent layer” in the baseline is a future target, not a mandatory first implementation. Start with the bounded registry in `docs/09_AI_AGENT_REGISTRY_AND_GOVERNANCE.md`. An agent is a permissioned workflow configuration, not an independently privileged service. Tools enforce permissions outside the model. Quota fallback must never bypass provider rate limits or account restrictions.

## F. Legal and tax settings

Existing GST, SAC, income-tax and presumptive-tax entries are configurable business placeholders only. A qualified Indian CA/legal adviser must confirm applicability, thresholds, wording and invoice treatment before use with real clients. Do not generate legal/tax conclusions automatically.

## G. Implementation deliverables

The complete v5.3 package includes:
- Preserved v5.2 Master SRS baseline.
- Product scope and acceptance.
- Architecture and runtime topology.
- Current free-provider assessment.
- OCI capacity and instance plan.
- Environment and release strategy.
- Database ERD/data dictionary.
- API contract and OpenAPI starter.
- UX navigation and screen specifications.
- AI agent registry/governance.
- Multilingual and voice engine.
- Integration register.
- Security/privacy controls.
- Test strategy and acceptance.
- CI/CD and GitHub workflow.
- Operations, backup and recovery.
- Implementation roadmap.
- Setup and go-live checklist.
- Docker Compose baseline, `.env.example`, CI workflow and release pipeline diagram.

## H. Account-specific verification still required

This package cannot inspect the user's OCI, GCP, GitHub, DNS, Neon, R2 or provider dashboards. Before provisioning, record actual:
- VM shape, RAM, OCPU, boot volume, AD and region;
- block-volume usage and remaining quota;
- public IP and inbound network rules;
- GCP project billing status and e2-micro region;
- provider account eligibility, current free quotas and data terms;
- domain DNS control and certificate status.

Do not destroy or recreate existing instances to chase capacity. Preserve working systems and use official quota/capacity diagnostics.


---

# Version 5.3.1 — Mandatory Zero-Cost Guard Amendment

**Priority: P0 / release-blocking.** This amendment is mandatory and supersedes any weaker interpretation of provider quota monitoring in previous sections.

## 1. Zero-cost default

The platform must start in `ZERO_COST_ONLY` mode:
- paid-service access disabled;
- automatic plan upgrades disabled;
- auto top-up disabled;
- paid fallback disabled;
- maximum approved monthly paid spend = INR 0;
- no provider may be enabled merely because an API key exists.

## 2. Automatic quota protection

Implement a central Quota Governance module with provider adapters, local metering, provider usage reconciliation, atomic quota reservation, circuit breakers, queue pausing, alerts and immutable audit events.

At minimum, meter:
- Cloudflare R2 storage, Class A/B operations and upload/download bytes;
- Neon compute, database storage and network transfer;
- Upstash data size, commands and bandwidth;
- OCI compute shapes, VM count, block volumes and outbound transfer;
- each AI/speech provider's model-specific token/character/audio/request allowance.

Use provider-reported usage where available. Where provider metrics are delayed, incomplete or unavailable on Free plans, use local estimates and conservative reserves; mark estimates clearly. If the metric is stale or unknown, block optional billable operations (fail closed).

## 3. Automatic stop

At the configured hard-stop threshold (default 95% of the internal free allowance, with a configurable 10–20% reserve based on metric quality):
- deny new optional billable requests before they start;
- stop optional uploads, AI generation, analytics refreshes and background jobs;
- pause queues and notify the founder;
- preserve core records and transactional integrity;
- do not automatically switch to a paid provider or plan.

## 4. Paid usage requires explicit founder approval

A paid override must specify provider, exact product, plan, purpose, INR spend cap, duration, data classification and expiry. It must be approved by the Super Admin and recorded against an immutable payload. No agent or automation may approve it.

## 5. Provider-specific billing traps

- Cloudflare R2 analytics are not instantaneous; bandwidth analytics omit transfers below 100 KiB. Local metering and reserve are mandatory.
- Neon consumption-history v2 API is documented for usage-based paid plans; do not assume it is available to Free projects. Free-plan monitoring needs Console reconciliation plus local estimates.
- Upstash documents that adding a payment method upgrades all Free resources on that account to Pay-as-You-Go. The system must warn and freeze the integration if a payment method or plan change is detected; the founder must review before proceeding.
- OCI budgets are soft alerts, not hard spending caps. They cannot replace admission control and provisioning allow-lists.

Detailed requirements and acceptance tests: `docs/18_ZERO_COST_GUARD_AND_QUOTA_GOVERNANCE.md`.


---

# Version 5.3.2 — Category-Based Free Provider Pool & Quality-Preserving Failover

**Priority: P0.** This amendment extends the Zero-Cost Guard. It is not enough to stop a single provider when its quota is exhausted. The platform must maintain category-based pools of approved equivalent providers and automatically switch to the next eligible free provider where safe.

## Mandatory requirements

1. Maintain provider pools for every external resource category: relational databases, object storage, cache/queues, AI/LLM, speech/transcription/translation, transactional email, hosting/compute, search, monitoring/analytics, DNS/CDN and other integrations.
2. Provider selection must check quota, billing state, plan verification, capability, privacy, region, quality, health, latency and capacity.
3. Stateless/idempotent tasks may switch automatically after quality and policy checks.
4. Stateful resources require data integrity and synchronization checks. A database endpoint must never be switched merely by changing `DATABASE_URL`.
5. Email and file operations require idempotency/checksum protection to avoid duplicate sends or corrupted/missing objects.
6. Every category defines minimum professional quality thresholds and benchmark evidence.
7. If one provider is exhausted, continue with the next eligible free provider. If no eligible free provider remains, pause only the affected category and preserve other core application workflows.
8. Never automatically switch to a paid provider, enable pay-as-you-go, upgrade a plan or add a payment method.
9. Provider pools and failover must be configurable and auditable. A provider is not eligible until its free quota, terms, privacy, capability and account eligibility have been verified.
10. Provider failover must be tested before being enabled in production.

Detailed architecture, current provider examples, category policies, database model additions, quality framework and acceptance tests are in:
`docs/19_CATEGORY_BASED_PROVIDER_POOLS_AND_FAILOVER.md`.

## Initial provider pool examples (not pre-approved account entitlements)

- PostgreSQL: Neon Free, Supabase Free, OCI-hosted PostgreSQL (capacity-dependent).
- Object storage: Cloudflare R2, Tigris, OCI Object Storage, Backblaze B2 (verify current plan).
- AI: Gemini Free, Groq Free, Cerebras Free/Developer (verify current model/rate-limit and privacy terms).
- Transactional email: Brevo Free, Resend Free, MailerSend Free (approval/limits apply).
- Cache/queue: Upstash Free, self-hosted Redis/Valkey or DB-backed queue (capacity-dependent).
- Speech: Azure Speech F0, Gemini voice/audio where eligible, Sarvam after current plan/terms verification.

These are candidates for evaluation, not guaranteed simultaneously available free services. Plan, eligibility, quota and terms must be rechecked before activation.


---

# v6.1 Addendum — Clarifications and Superseding Decisions

1. The legacy 26-agent arrangement is not a first-release requirement; use one orchestrator and dynamic capability workers.
2. Legacy assumptions of free Hugging Face Docker compute, OCI 4 OCPU/24 GB Always Free, unrestricted provider quota rotation, browser fingerprint evasion and automated anti-bot bypass are not accepted as guaranteed or permitted baselines.
3. Staging is mandatory for initial controlled production; it may be temporary/reusable and may run on a protected shared host with strict isolation.
4. Production hosting is optional and chargeable; it must be capacity-admitted and contractually scoped.
5. Kubernetes is deferred; Docker Compose is the initial multi-application deployment manager.
6. FastAPI is selected as the single primary backend baseline; do not operate parallel Django/FastAPI backends.
7. Ordinary runtime settings cannot weaken protected governance invariants.
8. External provider use must follow verified plan/terms, privacy, quota and quality eligibility.
9. Production idle reclamation and PAYG behavior must be confirmed with Oracle for the exact tenancy; do not assume PAYG alone guarantees Always Free 24×7 retention.
10. RPO/RTO, retention periods, service SLAs and hosting capacity remain business decisions to be approved after measurement; do not invent guarantees.

> NOTE (T-024, 2026-11-15): the object-storage bucket named in this SRS
> as `aknja-digital-artifacts` was renamed to `aknja-artifacts`; the
> semantics are unchanged.
