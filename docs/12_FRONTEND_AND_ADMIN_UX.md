# Frontend and Admin UX Specification

## Main navigation
Operations Interface: Overview, Leads, Clients, Service Catalog, Quotes/Contracts, Projects, Tasks, QA, Staging/UAT, Releases, Hosting, Incidents, Support, Reports.

System Control Interface: AI Orchestrator, Capability Registry, Tool Permissions, Provider Registry, Quota Control Centre, Environments, Audit, Security, Protected Policy (read-only view + controlled change workflow), System Health.

## UI states
Every data-driven screen must define loading, empty, error, permission-denied, quota-blocked, stale-data, pending-approval and success states. Do not display fabricated counters or sample data as live metrics. Label demo/test data.

## Visual design QA
Use exact viewport sizes, browser version, font availability, locale, color scheme and test data. Capture screenshots for key pages. Compare reference designs with controlled tolerances and review dynamic regions separately. Accessibility checks include keyboard focus, labels, contrast and responsive touch targets.
