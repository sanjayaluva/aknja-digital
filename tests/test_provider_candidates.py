"""Free-tier candidate provider workflow tests (docs/33, v5.3.2, SRS §9, doc 34).

Rules under test:
- the documented candidate pool seeds as FREE_UNVERIFIED + disabled;
- unverified candidates are NEVER admitted by the quota engine (fail closed);
- `verify-provider` records evidence, flips to FREE_VERIFIED and only then
  can the pool admit usage;
- re-running the candidate seed never flips an already-verified account back;
- doc-sourced additions (Colab, Modal, Jina, CF Pages) are present and
  Hugging Face is inference-only (Spaces Docker hosting withdrawn);
- web-researched watchlist entries carry research provenance (doc 34).
"""

from __future__ import annotations

from app.core.enums import BillingState, ProviderCategory
from app.modules.resources import service as quota
from app.modules.resources.candidates import CANDIDATE_PROVIDERS, register_candidate_providers
from app.modules.resources.models import ProviderAccount, ProviderProduct


def test_candidate_pool_covers_all_documented_categories(db, seed) -> None:
    stats = register_candidate_providers(db, seed.tenant.id)
    db.commit()
    assert stats["accounts"] == len(CANDIDATE_PROVIDERS)
    assert stats["products"] >= 20  # multiple metered products per provider
    categories = {
        p.category for p in db.query(ProviderProduct).all()
    }
    assert categories == {
        ProviderCategory.RELATIONAL_DB.value,
        ProviderCategory.OBJECT_STORAGE.value,
        ProviderCategory.AI_LLM.value,
        ProviderCategory.TRANSACTIONAL_EMAIL.value,
        ProviderCategory.CACHE_QUEUE.value,
        ProviderCategory.SPEECH.value,
        ProviderCategory.HOSTING_COMPUTE.value,
        ProviderCategory.SEARCH.value,
        ProviderCategory.MONITORING_ANALYTICS.value,
    }


def test_doc_sourced_additions_present_with_docs_provenance(db, seed) -> None:
    """Colab, Modal, CF Pages, Jina (doc-sourced); HF is inference-only now."""
    register_candidate_providers(db, seed.tenant.id)
    db.commit()
    by_provider = {
        a.provider: a for a in db.query(ProviderAccount).all()
    }
    for name in ("colab", "modal", "cloudflare_pages", "jina", "huggingface"):
        assert name in by_provider, f"{name} missing from candidate pool"
        assert by_provider[name].billing_state == BillingState.FREE_UNVERIFIED.value

    # HF Spaces Docker hosting was withdrawn from the free tier (2026-07):
    # the huggingface account must carry ONLY the inference product.
    hf_products = (
        db.query(ProviderProduct)
        .join(ProviderAccount, ProviderProduct.account_id == ProviderAccount.id)
        .filter(ProviderAccount.provider == "huggingface")
        .all()
    )
    assert [p.product_key for p in hf_products] == ["hf serverless inference"]
    assert all(p.category == ProviderCategory.AI_LLM.value for p in hf_products)
    assert "NOT a free hosting option" in hf_products[0].capability_contract["provider_note"]

    colab = next(
        p
        for p in db.query(ProviderProduct).join(
            ProviderAccount, ProviderProduct.account_id == ProviderAccount.id
        ).filter(ProviderAccount.provider == "colab").all()
    )
    assert colab.capability_contract["provenance"] == "docs"
    assert "opportunistic" in colab.capability_contract["provider_note"]


def test_watchlist_entries_carry_research_provenance(db, seed) -> None:
    """Web-researched candidates (doc 34) are tagged with the research date."""
    register_candidate_providers(db, seed.tenant.id)
    db.commit()
    watchlist = {"cloudflare_workers_ai", "github_models", "uptimerobot",
                 "better_stack", "brave_search", "tavily", "redis_cloud"}
    rows = (
        db.query(ProviderAccount)
        .filter(ProviderAccount.provider.in_(watchlist))
        .all()
    )
    assert {r.provider for r in rows} == watchlist
    for row in rows:
        assert row.billing_state == BillingState.FREE_UNVERIFIED.value
        assert row.enabled is False
    contract = (
        db.query(ProviderProduct)
        .join(ProviderAccount, ProviderProduct.account_id == ProviderAccount.id)
        .filter(ProviderAccount.provider == "cloudflare_workers_ai")
        .one()
        .capability_contract
    )
    assert contract["provenance"] == "web:2026-11-14"
    assert contract["documented_allowance"] == "10,000 Neurons/day"
    assert contract["docs_url"] == (
        "https://developers.cloudflare.com/workers-ai/platform/pricing"
    )


def test_candidates_seed_unverified_disabled_and_fail_closed(db, seed) -> None:
    register_candidate_providers(db, seed.tenant.id)
    db.commit()
    accounts = db.query(ProviderAccount).all()
    assert accounts
    for account in accounts:
        assert account.billing_state == BillingState.FREE_UNVERIFIED.value
        assert account.enabled is False  # candidates never start enabled (docs/33)
    products = db.query(ProviderProduct).all()
    assert products
    for product in products:
        assert product.allowance == 0  # unknown → fail closed

    # The documented free AI pool (gemini/groq/cerebras/...) is NOT admitted.
    for _ in range(1):
        decision = quota.admit_usage(
            db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM,
            quantity=1, idempotency_key="cand-llm-1",
        )
        assert decision.admitted is False
        assert "no eligible FREE_VERIFIED" in decision.reason
    decision_mail = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.TRANSACTIONAL_EMAIL,
        quantity=1, idempotency_key="cand-mail-1",
    )
    assert decision_mail.admitted is False


def test_candidate_seed_is_idempotent_and_preserves_verification(db, seed) -> None:
    register_candidate_providers(db, seed.tenant.id)
    db.commit()
    # Founder verifies + enables groq through the CLI logic.
    account = (
        db.query(ProviderAccount)
        .filter(ProviderAccount.provider == "groq")
        .one()
    )
    product = (
        db.query(ProviderProduct)
        .filter(ProviderProduct.account_id == account.id)
        .one()
    )
    account.billing_state = BillingState.FREE_VERIFIED.value
    account.enabled = True
    product.allowance = 1000
    product.enabled = True
    quota.record_snapshot(db, product, locally_metered=0)
    db.commit()

    # Re-seeding must not flip the verified account back to unverified.
    stats = register_candidate_providers(db, seed.tenant.id)
    db.commit()
    assert stats["accounts"] == 0  # all accounts already existed
    assert account.billing_state == BillingState.FREE_VERIFIED.value
    assert account.enabled is True
    assert product.allowance == 1000

    # And now the pool admits usage from the verified provider.
    decision = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM,
        quantity=5, idempotency_key="cand-verified-1",
    )
    assert decision.admitted is True
    assert decision.provider_product_id == product.id


def test_gemini_candidate_carries_privacy_warning(db, seed) -> None:
    """The free Gemini tier trains on content — the registry must say so."""
    register_candidate_providers(db, seed.tenant.id)
    db.commit()
    product = (
        db.query(ProviderProduct)
        .join(ProviderAccount, ProviderProduct.account_id == ProviderAccount.id)
        .filter(ProviderAccount.provider == "gemini")
        .one()
    )
    contract = product.capability_contract
    assert "improve" in contract["provider_note"] or "PRIVACY" in contract["provider_note"]
    assert contract["docs_url"] == "https://ai.google.dev/gemini-api/docs/pricing"
    assert contract["documented_allowance"] == "unknown"  # no invented quota


def test_documented_quota_metadata_is_doc_sourced(db, seed) -> None:
    """Reference figures come from v5.3.2 with source URLs — never invented."""
    register_candidate_providers(db, seed.tenant.id)
    db.commit()
    by_provider = {
        (a.provider, p.product_key): p
        for a in db.query(ProviderAccount).all()
        for p in db.query(ProviderProduct).filter(ProviderProduct.account_id == a.id).all()
    }
    r2_storage = by_provider[("cloudflare_r2", "r2 standard storage")]
    assert r2_storage.capability_contract["documented_allowance"] == "10 GB-month"
    brevo = by_provider[("brevo", "brevo free daily sends")]
    assert brevo.capability_contract["documented_allowance"] == "300/day"
    assert brevo.capability_contract["docs_url"].startswith("https://help.brevo.com/")
    neon = by_provider[("neon", "neon-free cu-hours/project/month")]
    assert "100 CU-hours" in neon.capability_contract["documented_allowance"]
