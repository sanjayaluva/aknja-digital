# Service Catalog and Blueprint Framework

The supplied taxonomy is the catalog scope, not proof that each service is currently deliverable. Preserve all leaf entries and tag them with truthful readiness.

## Required entities
`ServiceCategory`, `ServiceSubcategory`, `Service`, `ServiceVersion`, `ServiceBlueprint`, `ServiceInputDefinition`, `CapabilityRequirement`, `ToolRequirement`, `ServiceWorkflow`, `ServiceTaskTemplate`, `DeliverableContract`, `QARequirement`, `ApprovalRequirement`, `PricingPackage`, `ServiceAvailability`, `ServiceReadinessEvidence`.

## Blueprint stages
1. Definition and scope.
2. Required inputs and prerequisites.
3. Feasibility and capability check.
4. Plan, estimate and risks.
5. Task graph and execution.
6. Service-specific QA.
7. Client review/approval.
8. Deliverables and handover.
9. Warranty/maintenance/support options.

## Readiness promotion
`PLANNED → LIMITED → READY`. Promotion requires verified tool access, workflow, permissions, privacy, quota, capacity, QA checklist, evaluation cases and sample evidence. A service may remain catalogued while not available for sale.

## Execution modes
`MANUAL`, `AI_ASSISTED`, `SEMI_AUTONOMOUS`, `AUTONOMOUS_WITH_APPROVAL`, `AUTONOMOUS_LOW_RISK`.

## Family blueprint packs
- Web/API/CMS/e-commerce: discovery → architecture/UI → implementation → API/data/security tests → staging/UAT.
- Mobile/desktop: platform prerequisites, SDK/toolchain, signing accounts and device/store testing; client account/hardware may be required.
- Cloud/DevOps: infrastructure inventory, IaC plan, approval, deploy, smoke, backup/rollback.
- Data/AI: data rights/classification, dataset validation, model/tool selection, evaluation, privacy and reproducibility.
- IoT/embedded: hardware model, firmware build, simulator/unit tests, physical device validation as separate prerequisite.
- Scraping/RPA: authorized scope, robots/terms review, rate limits; no anti-bot evasion or access-control bypass.
- Security: written authorization, scope, safe test window, evidence, remediation; no unauthorized testing.
- QA: requirements traceability, test plan, automation, visual comparison, defect/retest/regression.
- SEO: crawl/index audit, keyword/content plan, technical fixes, analytics measurement; no ranking guarantee.
- Content/creative/video: brief, rights/licensing, scripts/assets, production, format/quality checks.
- Social/paid media: client account authorization, consent, budget, campaign approval; paid campaigns remain paused by default.
- Messaging/email: opt-in, official provider, suppression/bounce management, rate limits and compliance.
- CRO/analytics: consent-aware tracking, event validation, experiment design, reporting.
- ORM/PR/affiliate: truthful review workflows, partner permissions, disclosure, payout/legal controls.

Every leaf service must have a concrete blueprint before its readiness can be `READY`.
