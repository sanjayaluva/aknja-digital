# Episodic memory — provider verification workflow (2026-11-14)

**Scope:** EPISODIC · **Sensitivity:** INTERNAL · **Approved:** yes (founder-reviewed)

## What was built

The zero-cost provider lifecycle: `register-provider-candidates` seeds 32
provider accounts / 36 metered products as FREE_UNVERIFIED and disabled —
observation, not entitlement. Activation requires the audited
`verify-provider` CLI step: console-verified allowance, evidence note, and
`--enable`. Quota admission only ever accepts FREE_VERIFIED + enabled +
free products; stale or unknown quota snapshots fail closed; reservations
are row-locked so concurrent admissions cannot oversubscribe; 95% hard stop;
circuit breaker per product; free-pool failover before giving up.

## Decisions worth remembering

- Watchlist entries carry a research date + source URL and are never treated
  as entitlements (docs/34).
- Hugging Face Spaces Docker/Gradio hosting was withdrawn from the free pool
  on 2026-11-14 after HF moved it to paid plans (PRO/Team/Enterprise); the
  SRS §2.1 staging profile `UNIFIED_STAGING_HF_NEON` got an erratum — free
  staging rebases onto OCI Always-Free ARM. HF stays as inference-only.
- When a doc-sourced assumption is invalidated by reality, the fix is an
  erratum next to the original table (audit trail), not a silent rewrite.

**Provenance:** commits 2962cba, 005aee9; `tests/test_quota.py`,
`tests/test_provider_candidates.py`; docs/33, docs/34; SRS §2.1 erratum.
