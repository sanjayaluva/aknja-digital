# Architecture Overview

A modular monolith is the initial application architecture. Modules communicate through explicit service interfaces and durable database records. External compute and provider integrations are adapters.

Core planes:
- **Control plane:** FastAPI API, admin UI, authentication, service catalog, clients, projects, billing, approvals, audit.
- **Orchestration plane:** Central AI Orchestrator, capability registry, task planner, workflow state machine.
- **Execution plane:** isolated task workspaces, CI runners, browser QA, temporary staging, media/GPU batch runners.
- **Resource plane:** provider registry, quota ledger, admission controller, scheduler, circuit breakers.
- **Delivery plane:** artifact registry, staging/UAT, release approval, optional managed production.
- **Operations plane:** monitoring, incident response, backup, restore, maintenance and support.

Do not make free external services mandatory for core CRM/project functions. If AI or a provider is unavailable, manual workflows remain usable.
