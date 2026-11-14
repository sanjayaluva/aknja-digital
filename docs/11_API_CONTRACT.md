# API Contract

Prefix `/api/v1`. OpenAPI generated from FastAPI is authoritative. All errors use a stable envelope:
```json
{"error":{"code":"RESOURCE_NOT_FOUND","message":"Resource not found","request_id":"...","details":{}}}
```
Core route groups:
- `/auth/*`, `/users/*`, `/tenants/*`
- `/clients/*`, `/leads/*`, `/proposals/*`, `/contracts/*`
- `/services/*`, `/service-blueprints/*`, `/packages/*`
- `/projects/*`, `/requirements/*`, `/milestones/*`, `/tasks/*`
- `/approvals/*`, `/audit-events/*`
- `/providers/*`, `/quotas/*`, `/resource-jobs/*`
- `/environments/*`, `/releases/*`, `/deployments/*`
- `/uat/*`, `/feedback/*`, `/deliverables/*`
- `/hosting/*`, `/monitors/*`, `/incidents/*`, `/backups/*`
- `/admin/settings/*`, `/health/live`, `/health/ready`

Mutating operations require authorization, CSRF protection where cookie-authenticated, idempotency keys for retryable actions, and audit events. Pagination is cursor-based. Tenant scope is derived from authenticated membership, never trusted from arbitrary client input.
