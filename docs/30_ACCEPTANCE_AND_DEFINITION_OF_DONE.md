# Acceptance Criteria and Definition of Done

A feature is done only when:
- requirement and acceptance criteria are linked;
- authorization/tenant isolation is tested;
- implementation and migrations are reviewed;
- lint/type/unit/integration/contract tests pass;
- applicable E2E and visual checks pass;
- security/dependency/secret scans pass or documented risk accepted;
- docs/runbooks updated;
- staging deployment evidence exists;
- client acceptance recorded when required;
- release artifact/digest and rollback plan recorded;
- production approval and post-deploy checks recorded when production applies.

System release readiness additionally requires backup restore drill, incident drill, quota hard-stop tests, provider failover tests, access review and no unresolved critical vulnerabilities.
