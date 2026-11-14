"""Candidate free-tier provider registry (docs/33, v5.3.2 §5, SRS §8.4/§9).

Every entry below is a CANDIDATE, not an entitlement (docs/33): it is seeded
as `FREE_UNVERIFIED` + disabled with allowance unknown, so the quota engine
fails closed until the founder records verification evidence via
`python -m app.cli verify-provider`. Documented quota figures are copied from
`docs/source_provider_pools_v5.3.2.md` (with its source URLs) purely as
reference metadata — they are doc-time observations, not account truths.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import BillingState, ProviderCategory
from app.modules.resources.models import ProviderAccount, ProviderProduct

# (provider, category, display_name, secret_ref, docs_url, data_policy_note,
#  products: [(product_key, metric_key, unit, reset_period,
#              documented_allowance, documented_note)])
CANDIDATE_PROVIDERS: list[dict] = [
    # --- A. Relational database pool (v5.3.2 §5A) --------------------------
    {
        "provider": "neon",
        "category": ProviderCategory.RELATIONAL_DB,
        "display_name": "Neon Free PostgreSQL",
        "secret_ref": "DATABASE_URL (neon.tech endpoint)",
        "docs_url": "https://neon.com/docs/introduction/free-plan",
        "note": "Documented: 100 projects, 100 CU-h/project/month, 1 GB storage/project "
        "(20 GB account), 5 GB egress/project/month, scale-to-zero. Independent DB — "
        "never swap DATABASE_URL after quota exhaustion (v5.3.2 §5A warning).",
        "products": [
            ("neon-free cu-hours/project/month", "cu_hours", "cu-hours", "MONTHLY",
             "100 CU-hours/project/month", "per-project compute allowance"),
            ("neon-free storage-gb/project", "storage_gb", "GB-month", "MONTHLY",
             "1 GB/project (20 GB account)", "storage allowance"),
        ],
    },
    {
        "provider": "supabase",
        "category": ProviderCategory.RELATIONAL_DB,
        "display_name": "Supabase Free PostgreSQL",
        "secret_ref": "DATABASE_URL (supabase.co endpoint)",
        "docs_url": "https://supabase.com/pricing",
        "note": "Documented: 500 MB database, 5 GB egress, 1 GB file storage, project "
        "pausing after 1 week inactivity, 2 active projects.",
        "products": [
            ("supabase-free db-storage-mb", "storage_mb", "MB-month", "MONTHLY",
             "500 MB database", "database size allowance"),
        ],
    },
    # --- B. Object storage pool (v5.3.2 §5B) -------------------------------
    {
        "provider": "cloudflare_r2",
        "category": ProviderCategory.OBJECT_STORAGE,
        "display_name": "Cloudflare R2",
        "secret_ref": "R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY",
        "docs_url": "https://www.cloudflare.com/products/r2/",
        "note": "Documented: 10 GB-month Standard storage, 1M Class A + 10M Class B "
        "operations included; zero egress fees.",
        "products": [
            ("r2 standard storage", "storage_gb", "GB-month", "MONTHLY",
             "10 GB-month", "Standard storage included"),
            ("r2 class-a operations", "class_a_ops", "requests", "MONTHLY",
             "1,000,000/month", "Class A (write/list) operations"),
            ("r2 class-b operations", "class_b_ops", "requests", "MONTHLY",
             "10,000,000/month", "Class B (read) operations"),
        ],
    },
    {
        "provider": "tigris",
        "category": ProviderCategory.OBJECT_STORAGE,
        "display_name": "Tigris S3-compatible storage",
        "secret_ref": "TIGRIS_ACCESS_KEY_ID / TIGRIS_SECRET_ACCESS_KEY",
        "docs_url": "https://www.tigrisdata.com/pricing/",
        "note": "Documented: 5 GB Standard storage, 10k Class A + 100k Class B requests "
        "free monthly, no egress fees.",
        "products": [
            ("tigris standard storage", "storage_gb", "GB-month", "MONTHLY",
             "5 GB-month", "Standard storage included"),
        ],
    },
    {
        "provider": "backblaze_b2",
        "category": ProviderCategory.OBJECT_STORAGE,
        "display_name": "Backblaze B2 (S3-compatible API)",
        "secret_ref": "B2_KEY_ID / B2_APPLICATION_KEY",
        "docs_url": "",
        "note": "Pool candidate (v5.3.2 §5B). Verify current free tier and terms.",
        "products": [
            ("b2 storage", "storage_gb", "GB-month", "MONTHLY", "unknown", "verify in account"),
        ],
    },
    {
        "provider": "oci_object_storage",
        "category": ProviderCategory.OBJECT_STORAGE,
        "display_name": "OCI Object Storage (Always Free)",
        "secret_ref": "OCI credentials (kept outside Git)",
        "docs_url": "https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm",
        "note": "Documented: 20 GB combined Object Storage tiers and 50,000 API "
        "requests/month for Always Free-only accounts.",
        "products": [
            ("oci always-free storage", "storage_gb", "GB-month", "MONTHLY",
             "20 GB combined", "Always Free accounts only"),
            ("oci always-free api requests", "requests", "requests", "MONTHLY",
             "50,000/month", "Always Free accounts only"),
        ],
    },
    # --- C. AI / LLM inference pool (v5.3.2 §5C + SRS Layer 1) --------------
    {
        "provider": "gemini",
        "category": ProviderCategory.AI_LLM,
        "display_name": "Gemini API Free tier",
        "secret_ref": "GEMINI_API_KEYS",
        "docs_url": "https://ai.google.dev/gemini-api/docs/pricing",
        "note": "PRIVACY: Google states Free-tier content is used to improve its "
        "products — confidential client data must NOT be sent by default "
        "(v5.3.2 §5C). Limited model access and free token allowances; "
        "limits change per model.",
        "products": [
            ("gemini free tier", "requests", "requests", "DAILY", "unknown",
             "verify current per-model RPM/TPM in console"),
        ],
    },
    {
        "provider": "groq",
        "category": ProviderCategory.AI_LLM,
        "display_name": "Groq free developer access",
        "secret_ref": "GROQ_API_KEYS",
        "docs_url": "",
        "note": "Subject to current model/rate limits (v5.3.2 §5C). No rotation of "
        "keys/accounts to bypass limits.",
        "products": [
            ("groq free tier", "requests", "requests", "DAILY", "unknown",
             "verify current per-model rate limits"),
        ],
    },
    {
        "provider": "cerebras",
        "category": ProviderCategory.AI_LLM,
        "display_name": "Cerebras free tier",
        "secret_ref": "CEREBRAS_API_KEY",
        "docs_url": "https://inference-docs.cerebras.ai/support/pricing",
        "note": "Free tier has lower rate limits than paid tiers; do not confuse "
        "one-time credits with a perpetual allowance (v5.3.2 §5C).",
        "products": [
            ("cerebras free tier", "requests", "requests", "DAILY", "unknown",
             "verify eligibility and current limits"),
        ],
    },
    {
        "provider": "openrouter",
        "category": ProviderCategory.AI_LLM,
        "display_name": "OpenRouter `:free` models",
        "secret_ref": "OPENROUTER_API_KEY",
        "docs_url": "",
        "note": "SRS §8.4 Layer-1 candidate — only `:free` model slugs are allowed.",
        "products": [
            ("openrouter :free models", "requests", "requests", "DAILY", "unknown",
             "free model pool changes daily — verify"),
        ],
    },
    {
        "provider": "mistral",
        "category": ProviderCategory.AI_LLM,
        "display_name": "Mistral free experiment plan",
        "secret_ref": "MISTRAL_API_KEY",
        "docs_url": "",
        "note": "SRS §8.4 Layer-1 candidate; verify current free plan terms.",
        "products": [
            ("mistral free tier", "requests", "requests", "DAILY", "unknown",
             "verify current plan"),
        ],
    },
    {
        "provider": "huggingface",
        "category": ProviderCategory.AI_LLM,
        "display_name": "Hugging Face serverless inference",
        "secret_ref": "HF_TOKEN",
        "docs_url": "",
        "note": "Distinguish free static hosting (Spaces) from compute-backed "
        "hardware pricing (docs/33).",
        "products": [
            ("hf serverless inference", "requests", "requests", "DAILY", "unknown",
             "verify model availability and limits"),
        ],
    },
    # --- D. Transactional email pool (v5.3.2 §5D) --------------------------
    {
        "provider": "brevo",
        "category": ProviderCategory.TRANSACTIONAL_EMAIL,
        "display_name": "Brevo Free",
        "secret_ref": "BREVO_API_KEY",
        "docs_url": "https://help.brevo.com/hc/en-us/articles/208580669-FAQs-What-are-the-limits-of-the-Free-plan",
        "note": "Documented: 300 emails/day, up to 100,000 contacts, branding remains "
        "on free emails, transactional overflow queue up to 1,000 messages.",
        "products": [
            ("brevo free daily sends", "emails", "emails", "DAILY",
             "300/day", "daily send allowance"),
        ],
    },
    {
        "provider": "resend",
        "category": ProviderCategory.TRANSACTIONAL_EMAIL,
        "display_name": "Resend Free",
        "secret_ref": "RESEND_API_KEY",
        "docs_url": "https://resend.com/pricing",
        "note": "Documented: 3,000 emails/month, 100/day, 3 custom domains.",
        "products": [
            ("resend free daily sends", "emails", "emails", "DAILY",
             "100/day (3,000/month)", "daily + monthly caps"),
        ],
    },
    {
        "provider": "mailersend",
        "category": ProviderCategory.TRANSACTIONAL_EMAIL,
        "display_name": "MailerSend Free",
        "secret_ref": "MAILERSEND_API_KEY",
        "docs_url": "https://www.mailersend.com/help/plans-features-and-limits",
        "note": "Documented: up to 500 emails/month and 100/day after account "
        "approval; over-limit sends are not allowed on Free.",
        "products": [
            ("mailersend free daily sends", "emails", "emails", "DAILY",
             "100/day (500/month)", "approval required"),
        ],
    },
    # --- E. Cache / queue pool (v5.3.2 §5E) ---------------------------------
    {
        "provider": "upstash",
        "category": ProviderCategory.CACHE_QUEUE,
        "display_name": "Upstash Redis Free",
        "secret_ref": "REDIS_URL (upstash.io endpoint)",
        "docs_url": "",
        "note": "Cache must stay disposable; durable business jobs never live only "
        "in Redis (v5.3.2 §5E).",
        "products": [
            ("upstash free tier", "commands", "commands", "MONTHLY", "unknown",
             "verify current command/data limits"),
        ],
    },
    # --- F. Speech pool (v5.3.2 §5F) ----------------------------------------
    {
        "provider": "azure_speech",
        "category": ProviderCategory.SPEECH,
        "display_name": "Azure Speech F0",
        "secret_ref": "AZURE_SPEECH_KEY / AZURE_SPEECH_REGION",
        "docs_url": "",
        "note": "Test ml/en/hi/ta separately; compare WER, named-entity accuracy, "
        "timestamps (v5.3.2 §5F).",
        "products": [
            ("azure speech f0", "seconds", "audio-seconds", "MONTHLY", "unknown",
             "verify current F0 limits per locale"),
        ],
    },
    {
        "provider": "sarvam",
        "category": ProviderCategory.SPEECH,
        "display_name": "Sarvam AI (Indic languages)",
        "secret_ref": "SARVAM_API_KEY",
        "docs_url": "",
        "note": "Candidate for ml/hi/ta speech + translation; verify current free "
        "plan, locale coverage, privacy and rate limits (v5.3.2 §5F).",
        "products": [
            ("sarvam free tier", "requests", "requests", "DAILY", "unknown",
             "verify plan and locale coverage"),
        ],
    },
    # --- H. Hosting / compute pool (v5.3.2 §5H, docs/33, docs/14) -----------
    {
        "provider": "oci_a1",
        "category": ProviderCategory.HOSTING_COMPUTE,
        "display_name": "OCI Always Free A1 (ARM VM)",
        "secret_ref": "OCI credentials (kept outside Git)",
        "docs_url": "https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm",
        "note": "Use only the verified current tenancy allocation; confirm Always "
        "Free/idle reclamation conditions and volume quota (docs/33).",
        "products": [
            ("oci a1 vm", "ocpu_hours", "OCPU-hours", "MONTHLY", "unknown",
             "verify tenancy allocation (A1 shape, memory, boot volume)"),
        ],
    },
    {
        "provider": "github_actions",
        "category": ProviderCategory.HOSTING_COMPUTE,
        "display_name": "GitHub Actions (included minutes)",
        "secret_ref": "GITHUB_APP_ID / GITHUB_PRIVATE_KEY_SECRET_REF",
        "docs_url": "",
        "note": "Check included minutes/storage by repository visibility and plan "
        "(docs/33). CI within verified included minutes only (docs/14).",
        "products": [
            ("gh actions minutes", "minutes", "minutes", "MONTHLY", "unknown",
             "verify plan and repo visibility allowances"),
        ],
    },
    {
        "provider": "kaggle",
        "category": ProviderCategory.HOSTING_COMPUTE,
        "display_name": "Kaggle Notebooks (opportunistic GPU)",
        "secret_ref": "KAGGLE_USERNAME / KAGGLE_KEY",
        "docs_url": "",
        "note": "Interactive/best-effort GPU sessions — no durable service "
        "guarantee; checkpoint jobs (gpu_checkpoint_interval_min) and never "
        "upload confidential client assets (docs/14, docs/33).",
        "products": [
            ("kaggle gpu quota", "gpu_hours", "GPU-hours", "WEEKLY", "unknown",
             "verify current weekly GPU quota"),
        ],
    },
]


def register_candidate_providers(db: Session, tenant_id: uuid.UUID) -> dict[str, int]:
    """Idempotently seed every documented candidate as FREE_UNVERIFIED/disabled.

    Allowance stays 0 (unknown → fail closed). The documented figures are kept
    in `capability_contract` as reference metadata with their source note.
    """
    stats = {"accounts": 0, "products": 0, "skipped": 0}
    for candidate in CANDIDATE_PROVIDERS:
        account = db.scalar(
            select(ProviderAccount).where(
                ProviderAccount.tenant_id == tenant_id,
                ProviderAccount.provider == candidate["provider"],
            )
        )
        if account is None:
            account = ProviderAccount(
                tenant_id=tenant_id,
                provider=candidate["provider"],
                account_ref="default",
                display_name=candidate["display_name"],
                plan="FREE",
                billing_state=BillingState.FREE_UNVERIFIED.value,
                secret_ref=candidate["secret_ref"],
                data_policy_url=candidate["docs_url"],
                enabled=False,  # candidates never start enabled (docs/33)
                commercial_use_ok=False,
            )
            db.add(account)
            db.flush()
            stats["accounts"] += 1
        # Keep metadata fresh on re-runs without flipping verification state.
        account.data_policy_url = candidate["docs_url"] or account.data_policy_url
        for key, metric, unit, reset, documented, doc_note in candidate["products"]:
            product = db.scalar(
                select(ProviderProduct).where(
                    ProviderProduct.account_id == account.id,
                    ProviderProduct.product_key == key,
                )
            )
            if product is not None:
                stats["skipped"] += 1
                continue
            db.add(
                ProviderProduct(
                    account_id=account.id,
                    product_key=key,
                    category=candidate["category"].value,
                    capability_contract={
                        "candidate": True,
                        "documented_allowance": documented,
                        "documented_note": doc_note,
                        "provider_note": candidate["note"],
                        "docs_url": candidate["docs_url"],
                    },
                    metric_key=metric,
                    allowance=0,  # unknown → fail closed until verified
                    unit=unit,
                    reset_period=reset,
                    metric_source="LOCAL",
                    is_paid=False,
                    enabled=False,
                )
            )
            stats["products"] += 1
    db.flush()
    return stats
