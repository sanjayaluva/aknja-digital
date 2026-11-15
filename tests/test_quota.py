"""Quota engine tests: zero-cost guard, fail-closed, atomic reservations,
hard-stop, circuit breakers (Phase 4 exit criteria)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.orm import Session

from app.core.enums import BillingState, ProviderCategory, ReservationStatus
from app.core.errors import PolicyBlockedError
from app.modules.resources import service as quota
from app.modules.resources.models import QuotaReservation  # noqa: F401 (used by oversubscription sums)


def setup_product(db: Session, tenant_id, *, allowance=100, reported=0,
                  billing_state=BillingState.FREE_VERIFIED, is_paid=False,
                  enabled=True, confidence="MEDIUM", provider=None):
    import uuid as _uuid

    provider = provider or f"testcloud-{_uuid.uuid4().hex[:8]}"
    account = quota.register_provider_account(
        db, tenant_id=tenant_id, provider=provider, billing_state=billing_state.value, enabled=True
    )
    product = quota.register_provider_product(
        db, account=account, product_key="testcloud.free.tier", category=ProviderCategory.AI_LLM,
        allowance=allowance, is_paid=is_paid, enabled=enabled,
    )
    db.flush()
    quota.record_snapshot(db, product, provider_reported=reported, confidence=confidence)
    db.commit()
    return product


def test_zero_cost_mode_blocks_paid_products(db, seed) -> None:
    """ZERO_COST_ONLY: a paid product is never admitted (Phase 4 exit)."""
    setup_product(db, seed.tenant.id, is_paid=True, allowance=10_000, reported=0)
    decision = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM, quantity=1,
        idempotency_key="paid-test-1",
    )
    assert decision.admitted is False
    assert "no eligible" in decision.reason


def test_unverified_account_never_admitted(db, seed) -> None:
    """Candidate providers are not entitlements: FREE_UNVERIFIED fails closed."""
    setup_product(db, seed.tenant.id, billing_state=BillingState.FREE_UNVERIFIED)
    decision = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM, quantity=1,
        idempotency_key="unverified-test-1",
    )
    assert decision.admitted is False


def test_unknown_quota_fails_closed(db, seed) -> None:
    """No snapshot at all → unavailable (unknown quota fails closed)."""
    account = quota.register_provider_account(
        db, tenant_id=seed.tenant.id, provider="nosnap", enabled=True
    )
    quota.register_provider_product(
        db, account=account, product_key="nosnap.llm", category=ProviderCategory.AI_LLM, allowance=100
    )
    db.commit()
    decision = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM, quantity=1,
        idempotency_key="nosnap-test-1",
    )
    assert decision.admitted is False


def test_stale_quota_fails_closed(db, seed) -> None:
    from datetime import timedelta

    from app.core.security import utcnow
    from app.modules.resources.models import QuotaSnapshot

    product = setup_product(db, seed.tenant.id, allowance=100, reported=10)
    snap = db.query(QuotaSnapshot).filter(QuotaSnapshot.provider_product_id == product.id).one()
    snap.observed_at = utcnow() - timedelta(hours=25)
    db.commit()
    decision = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM, quantity=1,
        idempotency_key="stale-test-1",
    )
    assert decision.admitted is False
    assert "stale" in decision.reason or "no eligible" in decision.reason


def test_hard_stop_threshold_blocks_new_usage(db, seed) -> None:
    """95% hard-stop: usage at 95+ cannot reserve (default threshold 95%)."""
    setup_product(db, seed.tenant.id, allowance=100, reported=94)
    decision = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM, quantity=2,
        idempotency_key="hardstop-1",
    )
    assert decision.admitted is False
    # Below the cap it works.
    decision_ok = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM, quantity=1,
        idempotency_key="hardstop-2",
    )
    assert decision_ok.admitted is True


def _admit_in_thread(tenant_id, idempotency_prefix: str, quantity: int, index: int) -> bool:
    """Run an admission on its own session/connection (concurrency)."""
    import os

    from app.core.db import create_testing_engine
    from app.core.enums import ProviderCategory as PC

    session = Session(create_testing_engine(os.environ["DATABASE_URL"]))
    try:
        decision = quota.admit_usage(
            session, tenant_id=tenant_id, category=PC.AI_LLM, quantity=quantity,
            idempotency_key=f"{idempotency_prefix}-{index}",
        )
        session.commit()
        return decision.admitted
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def test_concurrent_reservations_serialize(db, seed) -> None:
    """6×10 units against allowance 100 (cap 95): all admitted, no errors."""
    setup_product(db, seed.tenant.id, allowance=100, reported=0)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda i: _admit_in_thread(seed.tenant.id, "loose", 10, i), range(6)))
    assert sum(1 for r in results if r) == 6


def test_concurrent_reservation_cannot_oversubscribe(db, seed) -> None:
    """4×10 units against allowance 25 (hard-stop cap 23.75): exactly 2 fit."""
    setup_product(db, seed.tenant.id, allowance=25, reported=0)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: _admit_in_thread(seed.tenant.id, "tight", 10, i), range(4)))
    admitted_tight = sum(1 for r in results if r)
    assert admitted_tight == 2, f"expected exactly 2 admissions, got {admitted_tight}"


def test_circuit_breaker_blocks_until_cooldown(db, seed) -> None:
    product = setup_product(db, seed.tenant.id, allowance=100, reported=0)
    quota.trip_circuit(db, product, failure_code="HTTP_429", cooldown_seconds=3600)
    db.commit()
    decision = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM, quantity=1,
        idempotency_key="breaker-1",
    )
    assert decision.admitted is False


def test_settle_and_release_reservations(db, seed) -> None:
    product = setup_product(db, seed.tenant.id, allowance=100, reported=0)
    decision = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM, quantity=5,
        idempotency_key="settle-1",
    )
    assert decision.admitted and decision.reservation_id
    settled = quota.settle_reservation(db, decision.reservation_id, actual_usage=4)
    assert settled.status == ReservationStatus.SETTLED.value
    # Usage rolled into the snapshot.
    from app.modules.resources.models import QuotaSnapshot

    snap = (
        db.query(QuotaSnapshot)
        .filter(QuotaSnapshot.provider_product_id == product.id)
        .order_by(QuotaSnapshot.observed_at.desc())
        .first()
    )
    assert snap.locally_metered_usage == 4

    decision2 = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM, quantity=3,
        idempotency_key="release-1",
    )
    released = quota.release_reservation(db, decision2.reservation_id)
    assert released.status == ReservationStatus.RELEASED.value


def test_paid_override_guard(db, seed) -> None:
    """Paid usage is blocked without an explicit founder override (v5.3.1 §4)."""
    with pytest.raises(PolicyBlockedError):
        quota.assert_paid_action_blocked()


def test_provider_failover_to_next_free_provider(db, seed) -> None:
    """Exhausted provider → next eligible free provider in the pool (v5.3.2)."""
    # First provider is above the hard stop.
    setup_product(db, seed.tenant.id, allowance=100, reported=95)
    # Second provider has plenty of room.
    healthy = setup_product(db, seed.tenant.id, allowance=1000, reported=10)
    decision = quota.admit_usage(
        db, tenant_id=seed.tenant.id, category=ProviderCategory.AI_LLM, quantity=5,
        idempotency_key="failover-1",
    )
    assert decision.admitted is True
    assert decision.provider_product_id == healthy.id
