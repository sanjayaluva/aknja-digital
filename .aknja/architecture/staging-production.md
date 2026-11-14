# Staging & Production Architecture

Staging is the primary delivery boundary and is reusable/temporary. Production hosting is optional, persistent and commercially contracted.

Staging lifecycle: provision isolated compose project → deploy exact tested artifact → seed synthetic data → run smoke/E2E/visual/security checks → client UAT → capture evidence → archive artifact/logs/screenshots → destroy environment and release resources after retention/approval.

Production lifecycle: client requests hosting → quote and contract → confirm client/Aknja host ownership → capacity admission → provision isolated project → secrets/DNS/TLS → backup baseline → deploy approved image digest → smoke test → monitoring/alerts → maintenance/incident plan.

Production projects must not share writable application data or secrets. A single host is not HA. Do not promise uptime/RPO/RTO beyond measured and contracted capability.
