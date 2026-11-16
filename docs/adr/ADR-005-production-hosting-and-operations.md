# ADR-005: Optional Managed Production Hosting

**Decision:** Aknja supports multiple isolated client applications on a production host using Docker Compose projects and a reverse proxy. Hosting is optional, priced and capacity-admitted. Each project has separate network, secrets, persistent storage and database/user boundary. One host is not HA.

**Operations:** monitoring, backup, maintenance, incident response and support are separately scoped. AI may perform safe reversible recovery; code/data/production changes require approval.
