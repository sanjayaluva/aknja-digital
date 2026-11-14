# Resource Plane & Quota-Aware Compute

The platform may use verified free-tier resources for eligible development, CI, batch and media workloads. Providers are not interchangeable by marketing category. Each provider product must pass capability, quota, billing, privacy, region, terms, quality, latency and capacity checks.

Flow: task classification → data classification → capability match → provider eligibility → quota snapshot freshness → atomic reservation → short-lived execution permit → checkpointed execution → output validation → usage reconciliation → release reservation.

Unknown/stale quota is unavailable for optional billable work. Paid fallback is disabled. Colab/Kaggle interactive notebooks are opportunistic batch runners, not durable production servers. Long-running jobs must be checkpointable and resumable.
