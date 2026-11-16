# ADR-003: Environment and Deployment Model

**Decision:** local → CI → temporary/reusable staging → client UAT → optional production. Build once and promote the same image digest.

**Staging:** protected, isolated, synthetic data, ephemeral by project or shared host with separate Compose project. Retain release evidence after cleanup.

**Production:** persistent; client-owned preferred; Aknja-managed optional and capacity/contract gated. No production cutover without exact-payload approval.
