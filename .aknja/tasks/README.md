# Task Record Contract

Every task should include: `task_id`, `project_id`, `tenant_id`, `goal`, `capability`, `inputs[]`, `data_classification`, `dependencies[]`, `acceptance_criteria[]`, `allowed_tools[]`, `resource_constraints`, `quota_reservation`, `approval_requirement`, `deadline`, `idempotency_key`, `status`, `artifacts[]`, `verification_evidence[]`, `failure_reason`, `created_at`, `updated_at`.

A task is `COMPLETED` only when acceptance criteria are independently verified and evidence is persisted. Partial work must be `PARTIAL` or `BLOCKED`.
