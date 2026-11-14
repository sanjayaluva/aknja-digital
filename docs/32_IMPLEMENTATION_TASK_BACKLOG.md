# Initial Implementation Backlog

Legend: ✅ done (test/CLI evidence in `.aknja/tasks/TASK_LOG.md`) · ◐ partial · ○ not started.
Status as of 2026-11-14 (round T-005). Updated every development round (protocol: `.aknja/README.md`).

## Epic A — Foundation — ✅ DONE (T-001)
A1 ✅ repository/app factory; A2 ✅ config/secrets; A3 ✅ PostgreSQL/Alembic; A4 ✅ health/logging; A5 ✅ CI.
## Epic B — Identity and governance — ✅ DONE (T-001)
B1 ✅ Super Admin auth; B2 ✅ RBAC/tenant scope; B3 ✅ audit ledger; B4 ✅ approval payload hashing; B5 ✅ emergency stop.
## Epic C — Service catalog — ✅ DONE (T-001)
C1 ✅ taxonomy import; C2 ✅ hierarchy CRUD; C3 ✅ blueprint schema; C4 ✅ readiness workflow; C5 ✅ packages/quotes.
## Epic D — Project delivery — ✅ DONE (T-001)
D1 ✅ clients/projects; D2 ✅ requirements/tasks; D3 ✅ milestones; D4 ✅ artifact store; D5 ✅ client portal/UAT.
## Epic E — AI and tools — ◐ MOSTLY (T-001, T-004, T-005)
E1 ✅ capability registry; E2 ✅ orchestrator state machine (+ LLM steps); E3 ◐ worker contract (dispatch design only); E4 ✅ Tool Gateway (+ llm.generate, data-class enforcement); E5 ○ evaluations (benchmark runner open, T-008).
## Epic F — Resource control — ✅ DONE (T-002)
F1 ✅ provider registry; F2 ✅ usage ledger; F3 ✅ quota snapshot; F4 ✅ atomic reservation; F5 ✅ hard stop; F6 ✅ category failover.
## Epic G — QA/staging — ◐ PARTIAL
G1 ◐ workspace runner (models/lifecycle in, provisioning needs a Docker host); G2 ○ Playwright; G3 ○ visual evidence; G4 ○ Compose environment manager; G5 ○ cleanup safety.
## Epic H — Production — ○ SPECIFIED, NOT DEPLOYED
H1 ○ host inventory; H2 ○ capacity manager; H3 ○ reverse proxy; H4 ○ deployment approvals; H5 ○ backups; H6 ◐ monitoring/incidents (Telegram admin notification outbox ✅ T-006; alert automation ongoing); H7 ○ maintenance billing. Requires capacity admission + drills per docs/19, docs/38; staging hosting rebased to OCI Always-Free ARM (SRS §2.1 erratum).
