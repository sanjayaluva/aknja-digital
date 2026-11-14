# QA, Functional and Visual Verification

## Test pyramid
- Unit: business logic, validators, quota math, state transitions.
- Integration: database, storage adapters, provider mocks, Tool Gateway.
- Contract: API schemas, webhooks, provider adapter normalization.
- E2E: critical client/admin workflows with Playwright.
- Visual: screenshot capture and design comparison at agreed breakpoints.
- Security: authz, tenant isolation, SSRF, upload validation, secrets, dependency/container scanning.
- Performance: baseline smoke and workload-specific load tests.
- UAT: client checklist and acceptance.

## Design-to-implementation verification
For each reference design, store version/hash, viewport, page state, font/assets and expected components. Compare screenshot output with controlled visual diff; exclude dynamic content regions explicitly. Track deviations with severity and owner. A human reviewer confirms visual acceptance.

## Completion gate
Every acceptance criterion has a test or documented manual verification. Failed tests block staging promotion. Critical/high security findings block release unless an explicit documented risk acceptance is approved by the founder and client as applicable.
