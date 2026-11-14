"""Resource/quota engine — Zero-Cost Guard + admission control (docs/13,
v5.3.1, v5.3.2).

Fail-closed rules:
- ZERO_COST_ONLY: paid/unverified products are never admitted;
- unknown or stale quota snapshots make a product unavailable;
- reservations are atomic (row-level lock) and cannot oversubscribe;
- hard-stop threshold (default 95%) blocks new optional usage;
- circuit-open products are skipped until cooldown passes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import BillingState, ProviderCategory, QuotaConfidence, ReservationStatus
from app.core.errors import PolicyBlockedError, QuotaExceededError
from app.core.security import generate_token, utcnow
from app.modules.resources.models import (
    CircuitBreaker,
    ProviderAccount,
    ProviderProduct,
    QuotaReservation,
    QuotaSnapshot,
    UsageEvent,
)

SNAPSHOT_STALE_AFTER = timedelta(hours=6)


@dataclass
class AdmissionDecision:
    admitted: bool
    provider_product_id: uuid.UUID | None = None
    reservation_id: uuid.UUID | None = None
    permit: str | None = None
    reason: str = ""


def register_provider_account(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    account_ref: str = "default",
    display_name: str = "",
    plan: str = "FREE",
    billing_state: str = BillingState.FREE_UNVERIFIED.value,
    region: str = "",
    secret_ref: str = "",
    enabled: bool = False,
) -> ProviderAccount:
    account = ProviderAccount(
        tenant_id=tenant_id,
        provider=provider,
        account_ref=account_ref,
        display_name=display_name or provider,
        plan=plan,
        billing_state=billing_state,
        region=region,
        secret_ref=secret_ref,  # name of env var/secret reference only
        enabled=enabled,
    )
    db.add(account)
    db.flush()
    return account


def register_provider_product(
    db: Session,
    *,
    account: ProviderAccount,
    product_key: str,
    category: ProviderCategory,
    metric_key: str = "requests",
    allowance: int = 0,
    unit: str = "count",
    is_paid: bool = False,
    enabled: bool = True,
) -> ProviderProduct:
    product = ProviderProduct(
        account_id=account.id,
        product_key=product_key,
        category=category.value,
        metric_key=metric_key,
        allowance=allowance,
        unit=unit,
        is_paid=is_paid,
        enabled=enabled,
    )
    db.add(product)
    db.flush()
    return product


def record_snapshot(
    db: Session,
    product: ProviderProduct,
    *,
    provider_reported: int | None = None,
    locally_metered: int | None = None,
    confidence: str = QuotaConfidence.MEDIUM.value,
) -> QuotaSnapshot:
    """Store a usage observation. Effective usage is the conservative max."""
    if provider_reported is not None and locally_metered is not None:
        effective = max(provider_reported, locally_metered)
        confidence = QuotaConfidence.HIGH.value if product.metric_source == "PROVIDER" else confidence
    elif provider_reported is not None:
        effective = provider_reported
        confidence = QuotaConfidence.MEDIUM.value
    else:
        effective = locally_metered or 0
        confidence = QuotaConfidence.MEDIUM.value if confidence != QuotaConfidence.HIGH.value else confidence
    snapshot = QuotaSnapshot(
        provider_product_id=product.id,
        metric_key=product.metric_key,
        allowance=product.allowance,
        provider_reported_usage=provider_reported,
        locally_metered_usage=locally_metered,
        effective_usage=effective,
        confidence=confidence,
        observed_at=utcnow(),
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def trip_circuit(
    db: Session, product: ProviderProduct, *, failure_code: str, cooldown_seconds: int | None = None
) -> CircuitBreaker:
    breaker = db.scalar(select(CircuitBreaker).where(CircuitBreaker.provider_product_id == product.id))
    if breaker is None:
        breaker = CircuitBreaker(provider_product_id=product.id, failure_count=0)
        db.add(breaker)
    breaker.state = "OPEN"
    breaker.failure_count = (breaker.failure_count or 0) + 1
    breaker.last_failure_code = failure_code[:16]
    breaker.tripped_at = utcnow()
    breaker.cooldown_until = utcnow() + timedelta(seconds=cooldown_seconds or 30)
    db.flush()
    return breaker


def _breaker_open(db: Session, product_id: uuid.UUID) -> bool:
    breaker = db.scalar(select(CircuitBreaker).where(CircuitBreaker.provider_product_id == product_id))
    if breaker is None or breaker.state != "OPEN":
        return False
    if breaker.cooldown_until is not None and breaker.cooldown_until <= utcnow():
        breaker.state = "HALF_OPEN"
        db.flush()
        return False
    return True


def _usage_state(
    db: Session, product: ProviderProduct
) -> tuple[QuotaSnapshot | None, float, str]:
    """Return (latest snapshot, utilization ratio 0..∞, failure reason)."""
    snapshot = db.scalar(
        select(QuotaSnapshot)
        .where(QuotaSnapshot.provider_product_id == product.id)
        .order_by(QuotaSnapshot.observed_at.desc())
        .limit(1)
    )
    if snapshot is None:
        return None, 0.0, "no quota snapshot (fail closed)"
    if snapshot.observed_at < utcnow() - SNAPSHOT_STALE_AFTER:
        return snapshot, 1_000_000.0, "stale quota snapshot (fail closed)"
    if snapshot.confidence == QuotaConfidence.STALE.value:
        return snapshot, 1_000_000.0, "low confidence snapshot (fail closed)"
    if product.allowance <= 0:
        return snapshot, 1_000_000.0, "allowance unknown (fail closed)"
    return snapshot, snapshot.effective_usage / product.allowance, ""


def admit_usage(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    category: ProviderCategory,
    quantity: int,
    task_id: uuid.UUID | None = None,
    idempotency_key: str,
    product_id: uuid.UUID | None = None,
    exclude_product_ids: list[uuid.UUID] | None = None,
) -> AdmissionDecision:
    """Reserve quota atomically from the best eligible free provider product.

    Implements the docs/13 reservation algorithm steps 1-6:
    classify → filter pool → reject ineligible → estimate → reserve → permit.

    `product_id` targets one specific product (provider "Test provider"
    action / llm-ping); `exclude_product_ids` lets the LLM failover loop
    move away from providers that just returned 429/5xx (v5.3.2 §3).
    """
    settings = get_settings()
    if settings.zero_cost_mode:
        # Zero-cost guard: nothing paid may ever be admitted.
        paid = db.scalars(
            select(ProviderProduct).join(ProviderAccount).where(
                ProviderAccount.tenant_id == tenant_id,
                ProviderProduct.category == category.value,
                (ProviderProduct.is_paid.is_(True))
                | (ProviderAccount.billing_state != BillingState.FREE_VERIFIED.value),
            )
        ).all()
        _ = paid  # listed for audit/debug; they are filtered out below anyway

    candidates = (
        select(ProviderProduct, ProviderAccount)
        .join(ProviderAccount, ProviderProduct.account_id == ProviderAccount.id)
        .where(
            ProviderAccount.tenant_id == tenant_id,
            ProviderProduct.category == category.value,
            ProviderProduct.enabled.is_(True),
            ProviderProduct.is_paid.is_(False),
            ProviderAccount.enabled.is_(True),
            ProviderAccount.billing_state == BillingState.FREE_VERIFIED.value,
        )
        .order_by(ProviderAccount.last_verified_at.desc().nullslast())
    )
    if product_id is not None:
        candidates = candidates.where(ProviderProduct.id == product_id)
    if exclude_product_ids:
        candidates = candidates.where(ProviderProduct.id.notin_(exclude_product_ids))
    rows = db.execute(candidates).all()
    if not rows:
        if product_id is not None:
            return AdmissionDecision(
                admitted=False,
                reason="target provider product is not eligible "
                "(must be FREE_VERIFIED, enabled, free, within quota)",
            )
        if exclude_product_ids:
            return AdmissionDecision(
                admitted=False,
                reason="no eligible FREE_VERIFIED provider product remains "
                "after excluding failed providers",
            )
        return AdmissionDecision(
            admitted=False,
            reason="no eligible FREE_VERIFIED provider product in this category",
        )

    rejection_reasons: list[str] = []
    for product, account in rows:
        if _breaker_open(db, product.id):
            rejection_reasons.append(f"{product.product_key}: circuit open")
            continue
        snapshot, _utilization, failure = _usage_state(db, product)
        if failure:
            rejection_reasons.append(f"{product.product_key}: {failure}")
            continue
        # --- Atomic reservation with hard-stop threshold. ---
        reservation = _reserve_with_lock(
            db,
            product=product,
            quantity=quantity,
            task_id=task_id,
            idempotency_key=idempotency_key,
            current_effective=snapshot.effective_usage if snapshot else 0,
            hard_stop_pct=settings.hard_stop_threshold_pct,
        )
        if reservation is None:
            rejection_reasons.append(
                f"{product.product_key}: would exceed hard-stop threshold "
                f"({settings.hard_stop_threshold_pct:g}%)"
            )
            continue  # try next provider in pool
        permit = generate_token("permit_")
        return AdmissionDecision(
            admitted=True,
            provider_product_id=product.id,
            reservation_id=reservation.id,
            permit=permit,
        )
    return AdmissionDecision(
        admitted=False,
        reason="all eligible providers exhausted or above hard-stop threshold; "
        + "; ".join(rejection_reasons),
    )


def _reserve_with_lock(
    db: Session,
    *,
    product: ProviderProduct,
    quantity: int,
    task_id: uuid.UUID | None,
    idempotency_key: str,
    current_effective: int,
    hard_stop_pct: float,
) -> QuotaReservation | None:
    """Row-lock the product so concurrent admissions cannot oversubscribe.

    Uses SELECT ... FOR UPDATE on the provider_products row as the
    serialization point (tested for concurrency in test_quota.py).
    """
    locked = db.execute(
        select(ProviderProduct).where(ProviderProduct.id == product.id).with_for_update()
    ).scalar_one_or_none()
    if locked is None:
        return None
    # Reserved-but-unsettled quantity from this product.
    reserved_qty = (
        db.query(QuotaReservation)
        .filter(
            QuotaReservation.provider_product_id == product.id,
            QuotaReservation.status == ReservationStatus.RESERVED.value,
        )
        .with_entities(QuotaReservation.quantity)
    )
    reserved_sum = sum(r[0] for r in reserved_qty)  # type: ignore[index]
    cap = product.allowance * (hard_stop_pct / 100.0)
    if current_effective + reserved_sum + quantity > cap:
        return None
    reservation = QuotaReservation(
        provider_product_id=product.id,
        task_id=task_id,
        quantity=quantity,
        unit=product.unit,
        idempotency_key=idempotency_key,
    )
    db.add(reservation)
    db.flush()
    return reservation


def settle_reservation(
    db: Session, reservation_id: uuid.UUID, *, actual_usage: int
) -> QuotaReservation:
    reservation = db.get(QuotaReservation, reservation_id)
    if reservation is None:
        raise QuotaExceededError("Reservation not found")
    if reservation.status != ReservationStatus.RESERVED.value:
        return reservation
    reservation.actual_usage = actual_usage
    reservation.status = ReservationStatus.SETTLED.value
    reservation.settled_at = utcnow()
    db.add(
        UsageEvent(
            provider_product_id=reservation.provider_product_id,
            reservation_id=reservation.id,
            quantity=actual_usage,
            unit=reservation.unit,
            source="LOCAL",
        )
    )
    # Roll actual usage into the latest snapshot so future admissions see it.
    product = db.get(ProviderProduct, reservation.provider_product_id)
    if product is not None:
        latest = db.scalar(
            select(QuotaSnapshot)
            .where(QuotaSnapshot.provider_product_id == product.id)
            .order_by(QuotaSnapshot.observed_at.desc())
            .limit(1)
        )
        if latest is not None:
            latest.locally_metered_usage = (latest.locally_metered_usage or 0) + actual_usage
            latest.effective_usage = max(
                latest.effective_usage or 0, latest.locally_metered_usage or 0
            )
            latest.observed_at = utcnow()
    db.flush()
    return reservation


def release_reservation(db: Session, reservation_id: uuid.UUID) -> QuotaReservation:
    reservation = db.get(QuotaReservation, reservation_id)
    if reservation is None or reservation.status != ReservationStatus.RESERVED.value:
        assert reservation is not None
        return reservation
    reservation.status = ReservationStatus.RELEASED.value
    reservation.settled_at = utcnow()
    db.flush()
    return reservation


def assert_paid_action_blocked() -> None:
    """Protected guard: paid usage requires an explicit founder override.

    There is no runtime setting that can disable this while
    ZERO_COST_ONLY is engaged (env-protected, ADR-004).
    """
    settings = get_settings()
    if settings.zero_cost_mode and (
        not settings.paid_fallback_enabled or settings.max_approved_monthly_spend_minor <= 0
    ):
        raise PolicyBlockedError(
            "ZERO_COST_ONLY: paid provider usage is blocked (no paid override approved)",
        )
