# Data Model and Database Design

Core entities (minimum):
- identity: `users`, `roles`, `user_roles`, `sessions`, `mfa_factors`;
- tenancy: `tenants`, `tenant_memberships`;
- business: `clients`, `contacts`, `leads`, `proposals`, `contracts`, `invoices`, `payments`;
- catalog: `service_categories`, `services`, `service_versions`, `service_blueprints`, `service_inputs`, `service_capabilities`, `deliverable_contracts`, `service_packages`;
- delivery: `projects`, `requirements`, `milestones`, `tasks`, `task_dependencies`, `artifacts`, `feedback`, `uat_acceptances`;
- AI: `agent_capabilities`, `agent_runs`, `memory_records`, `tool_definitions`, `tool_executions`;
- governance: `approval_requests`, `approval_decisions`, `audit_events`, `policy_versions`;
- resources: `provider_accounts`, `provider_products`, `quota_snapshots`, `usage_events`, `quota_reservations`, `provider_pools`, `circuit_breakers`;
- environments: `execution_environments`, `deployments`, `release_artifacts`, `release_approvals`, `environment_events`;
- operations: `monitors`, `alerts`, `incidents`, `backup_records`, `restore_drills`, `maintenance_contracts`, `support_tickets`.

Rules:
- UUID primary keys; UTC timestamps; money in integer minor units + ISO currency.
- Tenant ID on every tenant-owned row; composite constraints where feasible.
- Index tenant_id + common query keys; foreign keys and unique idempotency keys.
- Soft delete only where legal/operationally appropriate; preserve audit records.
- Audit append-only for application roles.
- Encrypt secrets outside DB; DB stores secret references only.
- Never use client-provided IDs without tenant-scoped lookup.
