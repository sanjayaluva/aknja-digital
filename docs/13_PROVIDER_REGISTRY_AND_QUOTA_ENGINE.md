# Provider Registry and Quota Engine

Preserve detailed source requirements in `source_zero_cost_guard_v5.3.1.md` and `source_provider_pools_v5.3.2.md`.

Required provider metadata:
provider, product, account reference, plan, billing state, region, capability contract, quota unit/allowance/reset, metric source, metrics delay, data policy, commercial-use eligibility, secret reference, health, quality benchmark, last verified time, enabled status.

Reservation algorithm:
1. classify task and data;
2. filter provider pool by terms/privacy/capability/region/quality/health;
3. reject paid-only, unverified, stale quota or hard-stopped providers;
4. estimate task resource usage;
5. atomically reserve with safety reserve;
6. issue short-lived permit;
7. execute with checkpoint;
8. reconcile actual usage;
9. release or settle reservation;
10. audit switch and evidence.

Free quota is not a guaranteed service entitlement. Do not rotate accounts or keys to evade limits. Paid override requires founder approval, exact provider/product, purpose, cap, duration, data class and expiry.
