# ADR-002: Central Orchestrator and Dynamic Specialists

**Decision:** One Central AI Orchestrator plus task-scoped specialist capability templates. No 26 permanent agents.

**Enforcement:** Tool Gateway, not model prompts, enforces permissions. Workers receive short-lived scoped execution context and return structured outputs with evidence. No self-approval, self-grant or policy mutation.
