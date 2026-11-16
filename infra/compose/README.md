# Compose Deployment Conventions

Use a unique project name per client, e.g. `docker compose -p client_<slug> -f compose.production.yml up -d`. Do not expose database ports publicly. Each client gets a dedicated network and persistent volume names. Use reverse proxy labels or a controlled proxy config. Set CPU/memory/PID limits based on host and application measurements. Store secrets outside the repository. Do not use `docker compose down -v` in production runbooks. Cleanup scripts must validate environment labels and require approval.
