# 19 — Category-Based Free Provider Pools & Quality-Preserving Failover

**Priority:** P0 architecture requirement  
**Default mode:** Free-only provider pools, automatic switching among pre-approved eligible providers  
**Paid fallback:** prohibited unless a Super Admin creates an explicit paid override  
**Relationship:** extends `docs/18_ZERO_COST_GUARD_AND_QUOTA_GOVERNANCE.md`

## 1. Requirement

For every external resource category used by Aknja Digital, maintain a pool of pre-approved providers with equivalent capabilities. When a provider reaches its internal free quota, becomes unavailable, or fails health/quality checks, the system should select the next eligible provider in that category and continue the operation without losing data or lowering the agreed quality threshold.

The system should stop only when:
1. no eligible free provider remains in the category;
2. remaining providers fail capability, quality, privacy, latency, capacity or compatibility checks;
3. a safe migration/switchover cannot be completed;
4. all free quota pools are exhausted or unknown; or
5. an explicit policy/approval gate blocks the operation.

**Never switch to a paid plan/provider automatically.**

## 2. Category pool model

Each category has:
- `category_key`: e.g. `relational_database`, `object_storage`, `llm_inference`, `transactional_email`.
- `provider_pool`: approved provider accounts and resource identifiers.
- `capability_contract`: required API/protocol, data model, region, consistency and feature support.
- `quality_profile`: measurable minimum service quality.
- `quota_policy`: per-provider quota, reset, safety reserve and hard stop.
- `priority_order`: preferred provider order, not a promise that it will be selected.
- `switch_strategy`: stateless retry, endpoint switch, replicated failover, asynchronous queue or manual migration.
- `data_sync_policy`: how data is replicated, verified and reconciled.
- `rollback_policy`: conditions and method to return to a previous provider.
- `last_verified_at`: current plan/quota/terms verification timestamp.

Do not treat providers as interchangeable merely because they share a marketing category. A provider is eligible only if it passes the category contract.

## 3. Provider selection algorithm

For every operation:

1. Resolve category and operation type.
2. Load providers in the approved pool.
3. Exclude disabled, paid-only, unverified, quota-hard-stopped, privacy-ineligible and unhealthy providers.
4. Check capability compatibility.
5. Check estimated remaining quota and reserve.
6. Check region/data residency requirements.
7. Check latency, reliability and capacity thresholds.
8. Check quality score for the specific workload.
9. Choose the highest-ranked eligible provider.
10. Atomically reserve quota before sending the operation.
11. Execute with idempotency key and bounded timeout.
12. Validate output/data integrity.
13. Record provider, quota, latency, result quality and failover event.
14. If the operation fails, retry only when safe; otherwise pause and escalate.

### Provider ranking

Use weighted scoring, with hard eligibility gates first:

- Capability match: mandatory pass/fail.
- Data/privacy suitability: mandatory pass/fail.
- Free quota availability: mandatory pass/fail.
- Data integrity/consistency: mandatory pass/fail for stateful services.
- Quality benchmark: mandatory minimum.
- Reliability and recent error rate.
- Latency and capacity.
- Operational cost: free providers rank above paid providers in `ZERO_COST_ONLY`.
- Switching cost and data egress implications.

Do not let a high aggregate score override a failed mandatory gate.

## 4. Switching classes

| Class | Example | Automatic switching allowed? | Required safeguards |
|---|---|---|---|
| Stateless request | LLM text draft, translation | Yes, within approved pool | Output quality benchmark, privacy policy, idempotency |
| Retryable delivery | Email send | Conditional | Message idempotency, duplicate prevention, sender-domain verification |
| Object storage | File upload/download | Conditional | S3/API compatibility, object checksum, copy/verify, signed URL refresh |
| Cache | Redis | Yes if cache is disposable | Cache key/version compatibility; no source-of-truth data |
| Relational database | PostgreSQL | Only with tested replication/failover | Replication lag, schema compatibility, transaction consistency, DNS/connection switch |
| Search index | Search provider | Yes if source DB is canonical | Rebuild/re-index capability, query contract |
| Monitoring/analytics | Metrics/log provider | Usually yes | Avoid loss of critical audit data; buffer locally |
| Authentication/identity | Identity provider | Restricted | Session/token compatibility, account recovery, security review |
| Payment/billing | Payment gateway | No silent switch | Explicit approval, reconciliation and duplicate-payment protection |

## 5. Category requirements

### A. Relational database pool

Possible candidates to evaluate:
- Neon Free PostgreSQL.
- Supabase Free PostgreSQL.
- OCI-hosted PostgreSQL on an existing VM, if memory/disk/backup capacity permits.
- Other PostgreSQL providers only after current Free plan and eligibility are verified.

Current provider examples are not a guarantee of account availability:
- Neon currently documents 100 projects, 100 CU-hours/project/month, 1 GB storage/project (up to 20 GB account total), 5 GB public network transfer/project/month, and scale-to-zero after inactivity. https://neon.com/docs/introduction/free-plan
- Supabase currently documents Free PostgreSQL with 500 MB database, 5 GB egress, 1 GB file storage and project pausing after one week of inactivity; only two active projects. https://supabase.com/pricing
- OCI Always Free includes 20 GB combined Object Storage tiers and 50,000 API requests/month for Always Free-only accounts; this is object storage, not a free managed PostgreSQL service. https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm

**Critical warning:** Neon and Supabase are both PostgreSQL, but that does not make a database endpoint switch safe by itself. They are independent databases. Aknja must not merely replace `DATABASE_URL` after quota exhaustion.

Required architecture:
- Canonical schema migrations tracked in Git.
- Database backup and tested restore.
- Continuous or scheduled replication only where supported and tested.
- Replication lag monitoring.
- Write freeze / maintenance mode during a controlled promotion if no safe zero-loss replication exists.
- Sequence/identity and extension compatibility checks.
- Data checksum and row-count reconciliation.
- Connection pool and TLS validation.
- Promotion approval policy.

For the first release, use **one active writable primary** and one tested standby/restore target. If no supported free cross-provider replication can maintain the required RPO, switch only after a controlled maintenance window and verified restore. Do not promise transparent zero-downtime database failover.

### B. Object storage pool

Candidates:
- Cloudflare R2.
- Tigris S3-compatible object storage.
- Backblaze B2 S3-compatible API.
- OCI Object Storage, within Always Free quota.

Current examples:
- R2: 10 GB-month Standard storage, 1M Class A and 10M Class B operations included; paid overage rates apply beyond included usage. https://www.cloudflare.com/products/r2/
- Tigris: current pricing page lists 5 GB Standard storage, 10,000 Class A and 100,000 Class B requests free monthly, with no egress fees; verify account terms and current page. https://www.tigrisdata.com/pricing/
- OCI: Always Free-only account includes 20 GB combined Object Storage tiers and 50,000 API requests/month. https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm

Requirements:
- Use an S3-compatible storage adapter where possible, but do not assume every provider supports identical semantics.
- Store provider, bucket, object key, checksum, size, content type, version and replication state in the DB.
- Use stable logical file IDs; never expose raw provider bucket paths to application modules.
- On migration, copy object, verify checksum and metadata, then update location mapping.
- Keep old copy until validation and retention policy permit deletion.
- Reissue signed URLs from the currently active provider.
- Check lifecycle, multipart upload, object-lock/versioning and maximum object size compatibility.
- Avoid duplicate upload on retry; use idempotency keys and checksum-based de-duplication.

### C. AI / LLM inference pool

Candidates to evaluate:
- Gemini API Free (only for permitted data classes).
- Groq free developer access, subject to current model/rate limits.
- Cerebras free/developer access where offered; current official pricing distinguishes free access and paid developer/enterprise capacity. Do not confuse a one-time credit with a perpetual free allowance.
- Other providers only after plan, rate limits, privacy terms and data use are verified.

Official examples:
- Gemini Free tier currently offers limited model access and free input/output tokens, but Google states Free-tier content is used to improve its products. Do not send confidential client data by default. https://ai.google.dev/gemini-api/docs/pricing
- Cerebras pricing currently distinguishes a free tier with lower rate limits from paid usage tiers; verify current model and eligibility. https://inference-docs.cerebras.ai/support/pricing

Requirements:
- Provider-neutral model gateway with task profiles: `classification`, `translation`, `summarization`, `requirements`, `code_review`, `proposal_draft`, `qa_review`.
- Each task profile defines minimum context window, structured-output support, tool/function-call support, language quality, maximum latency and safety policy.
- Maintain benchmark prompts and golden expected outputs for Malayalam, English, Hindi and Tamil.
- Score factuality, completeness, terminology preservation, JSON/schema validity, instruction adherence and latency.
- Do not replace a high-capability model with a smaller model if it fails the task's quality floor.
- Retry transient 429/5xx with backoff and jitter; do not rotate keys/accounts to bypass limits.
- If next provider has a different API schema, normalize request/response through adapter.
- For tool calls, validate the model's proposed tool arguments against application policy; never trust model output.
- Store provider/model and prompt-template version for reproducibility.
- If no free model meets the quality floor, queue for later, request founder review or provide a manual workflow. Do not silently degrade client deliverables.

### D. Transactional email pool

Candidates:
- Brevo Free.
- Resend Free.
- MailerSend Free (approval/eligibility may apply).
- SMTP on a domain-controlled mail service only if the provider's terms and deliverability are suitable.

Current examples:
- Brevo Free: 300 email sends/day; up to 100,000 contacts; branding remains on free emails; transactional overflow may queue up to 1,000 additional messages. https://help.brevo.com/hc/en-us/articles/208580669-FAQs-What-are-the-limits-of-the-Free-plan
- Resend Free: 3,000 emails/month, 100/day, 3 domains. https://resend.com/pricing
- MailerSend Free: after approval, up to 500 emails/month and 100/day; over-limit sends are not allowed on Free. https://www.mailersend.com/help/plans-features-and-limits

Requirements:
- Email adapter abstracts provider-specific APIs.
- Verify sender domain, SPF, DKIM and DMARC for every provider before production sending.
- Use a durable outbox with globally unique message ID and delivery state.
- Retry only when the first provider confirms that the message was not accepted; if acceptance status is unknown, query provider or hold for reconciliation to avoid duplicate email.
- Keep message content and attachments available for retry.
- Maintain suppression lists, bounce/complaint handling and rate limits.
- Provider failover must not bypass unsubscribe, consent or anti-spam rules.
- Marketing campaigns and bulk email require separate approval and quotas from transactional email.
- Do not assume sender reputation transfers between providers; warm-up and deliverability need monitoring.

### E. Cache / queue pool

Candidates:
- Upstash Redis Free.
- Self-hosted Redis/Valkey on OCI only if capacity permits.
- Database-backed job queue for low-volume jobs.

Requirements:
- Cache is disposable and can be rebuilt.
- Durable business jobs must not exist only in Redis.
- Queue messages include idempotency key, attempts, deadline and dead-letter state.
- Switching cache providers invalidates or versions cache namespace.
- Queue migration must drain or re-enqueue messages safely.
- Do not fail over to a paid cache automatically.

### F. Speech / transcription / translation pool

Candidates:
- Azure Speech F0.
- Gemini API voice/audio features where current Free access supports the required task and privacy is acceptable.
- Sarvam or other Indic-language services after verifying current free plan, locale coverage, privacy and rate limits.
- Local browser/device speech recognition as optional convenience only.

Requirements:
- Test Malayalam, English, Hindi and Tamil separately.
- Compare word error rate where reference transcripts exist, named-entity accuracy, punctuation, timestamp accuracy and translation adequacy.
- Keep source audio and transcript separate from translation.
- Do not switch mid-stream in a live call unless the session protocol supports it; finish or restart a segment safely.
- Never silently downgrade a client-visible transcription below the agreed confidence threshold.
- If no provider meets the locale/quality threshold, mark pending human transcription.

### G. Monitoring, error tracking, analytics and search

Use provider adapters and local durable buffers. Keep security audit events in the application database or a separately controlled durable store; do not rely solely on a free third-party analytics plan. Search indexes are rebuildable from the canonical database. A monitoring provider outage must not disable the application.

### H. Hosting and compute

Use OCI A1 VMs as the known baseline. Other free compute services can be registered as optional preview/worker pools only after region, runtime, sleep, ephemeral storage, ARM/x86 architecture, bandwidth, privacy and terms are checked. Do not automatically deploy core production workload to a free host that sleeps, suspends or has ephemeral storage.

## 6. Quality preservation framework

Every provider category must define a quality profile before automatic failover is enabled.

Examples:
- LLM: task-specific benchmark score, schema validity, language accuracy, hallucination review.
- Translation: named-entity preservation, terminology glossary, human-review threshold.
- Email: accepted/delivered/bounced/complaint rates, domain authentication, no duplicate sends.
- Database: replication lag, checksums, transaction integrity, backup freshness, RPO/RTO.
- Storage: checksum match, metadata integrity, access-control and signed URL validity.
- Speech: locale-specific word error rate and named-entity accuracy.
- Search: index freshness, result relevance and query correctness.

A provider that is cheaper or free but fails the quality floor is not eligible. Professional quality is a hard requirement, not a weighted preference that can be traded for cost.

## 7. Data model additions

Add these models alongside the quota models in document 18:

### `provider_categories`
`id`, `category_key UNIQUE`, `display_name`, `capability_contract_json`, `quality_profile_json`, `switch_strategy`, `default_mode`, `enabled`.

### `provider_pool_members`
`id`, `category_id`, `provider_product_id`, `priority`, `role` (primary/secondary/tertiary), `enabled`, `verified_at`, `health_state`, `quality_score`, `last_failover_at`.

### `provider_capabilities`
`id`, `provider_product_id`, `capability_key`, `capability_value_json`, `verified_at`.

### `provider_health_samples`
`id`, `provider_product_id`, `latency_ms`, `success_rate`, `error_rate`, `observed_at`, `source`.

### `provider_quality_benchmarks`
`id`, `category_id`, `task_type`, `benchmark_version`, `provider_product_id`, `score_json`, `passed`, `evaluated_at`.

### `provider_switch_events`
`id`, `category_id`, `from_provider_product_id`, `to_provider_product_id`, `reason`, `switch_class`, `data_sync_status`, `quality_check_status`, `approved_by nullable`, `started_at`, `completed_at`, `rollback_status`, `request_id`.

### `data_replication_checkpoints`
`id`, `source_resource_id`, `target_resource_id`, `checkpoint_ref`, `lag_seconds`, `checksum_status`, `row_count_status`, `verified_at`.

## 8. Dashboard requirements

Add **Provider Pool Manager** under Cost & Quota Control Centre.

Show:
- Category and provider pool members.
- Primary/secondary/tertiary status.
- Verified free quota and reset date.
- Current usage and remaining estimate.
- Provider health, latency, error rate and last successful check.
- Capability compatibility.
- Quality benchmark score and date.
- Data replication/synchronisation status.
- Current active provider.
- Failover history and reason.
- Automatic switching enabled/disabled per category.
- “Test provider” and “Run benchmark” actions.
- “Approve provider for pool” founder action.
- Paid providers must show as locked unless a paid override is active.

## 9. Failover policies

- `AUTO_SAFE`: stateless, idempotent operations with passed quality checks.
- `AUTO_WITH_VALIDATION`: object storage, email and rebuildable search after checksum/idempotency validation.
- `CONTROLLED_PROMOTION`: stateful databases; maintenance mode, replication verification and founder approval may be required.
- `MANUAL_ONLY`: payments, identity/authentication, legal signature, production DNS and any operation with irreversible financial/legal effect.

Default:
- LLM/stateless translation: `AUTO_SAFE` only after benchmark and data-policy approval.
- Email: `AUTO_WITH_VALIDATION`.
- Object storage: `AUTO_WITH_VALIDATION`.
- Cache: `AUTO_SAFE` if data is disposable.
- Database: `CONTROLLED_PROMOTION`.
- Payments/auth: `MANUAL_ONLY`.

## 10. Acceptance tests

- [ ] A provider reaching hard-stop is excluded from selection.
- [ ] The next eligible free provider is selected for a stateless operation.
- [ ] A paid provider is never selected in zero-cost mode.
- [ ] Provider with stale/unknown quota is excluded.
- [ ] Provider failing data/privacy requirements is excluded.
- [ ] Provider failing task quality benchmark is excluded.
- [ ] LLM response schema is normalized and validated across providers.
- [ ] Malayalam/English/Hindi/Tamil benchmark thresholds are checked independently.
- [ ] Object copy verifies checksum before logical location is changed.
- [ ] Email retry cannot send duplicate messages when acceptance state is unknown.
- [ ] Database failover refuses promotion when replication lag or checksum exceeds policy.
- [ ] Database failover enters maintenance mode when zero-loss switching cannot be guaranteed.
- [ ] Cache failover does not lose durable jobs.
- [ ] Provider switch is logged with source, target, reason, quota and quality evidence.
- [ ] Rollback path is tested for every enabled automatic switch class.
- [ ] If all eligible providers are exhausted, the system pauses only the affected category and notifies founder.
- [ ] Core CRM/project/document workflows remain available when optional external services are paused.

## 11. Operating principle

**Exhaust the approved free capacity across a category before stopping that category — but never sacrifice data integrity, privacy, quality, or professional delivery to achieve that goal.** Aknja should continue using the next compatible and quality-approved free provider. It should pause only the affected operation when no safe eligible provider remains. Paid services remain blocked until the founder explicitly authorizes them.
