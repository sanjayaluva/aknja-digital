# ADR-004: Zero-Cost-First Resource Strategy

**Decision:** ZERO_COST_ONLY by default; paid spend cap INR 0. External providers are optional adapters. Free-tier compute is best-effort, quota-aware and not an SLA.

**Allowed pattern:** provider verified → quota fresh → capability/privacy/terms match → atomic reservation → checkpointable job → output validation → usage reconciliation.

**Forbidden:** paid fallback, auto-upgrade, auto-top-up, account/key rotation to evade limits, using unknown quota, uploading confidential client data without authorization.
