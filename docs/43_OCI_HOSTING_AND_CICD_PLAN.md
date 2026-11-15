# OCI Free Hosting and CI/CD Deployment Plan

Status: plan (2026-11-15) — execution starts when the founder re-shares the
instance credentials (see "Inputs still missing"). Records the decisions of
2026-11-15: Modal withdrawn (paid), OCI chosen, default R2 bucket retained.

## Base

- 2 x OCI Always-Free instances described by the founder as 1 OCPU / 6 GB RAM
  / 50 GB storage each — shape consistent with A1.Flex (aarch64). Confirm
  `uname -m` on first login; the stack (Python 3.12, FastAPI, SQLite, Caddy,
  systemd) is arch-agnostic.
- docs/19 commercial gate does not apply: this is platform self-hosting, not
  client managed hosting. docs/38 admission (load test before publishing any
  client workload) still applies.

## Topology (proposal)

- Instance 1 — production: FastAPI app (systemd), SQLite, Caddy reverse proxy
  with automatic TLS, Telegram poller, `aknja backup push` on a systemd timer
  (existing R2 pipeline, docs/22), external /healthz uptime check
  (UptimeRobot, docs/34).
- Instance 2 — staging + restore-drill target + translation worker:
  IndicTrans2 en-indic-dist-200M (MIT, ~1.1 GB) behind a localhost FastAPI
  endpoint; the translation gateways gain a self-hosted free fallback for the
  Malayalam floor (docs/34, 2026-11-15 sweep).

## Deploy method: GitHub Actions CI/CD over SSH

Decision: CI/CD is the deploy path; direct SSH stays for ops/emergency only.
Why: the repository is public, so standard GitHub-hosted runners are free
(https://docs.github.com/billing/managing-billing-for-github-actions/about-billing-for-github-actions);
the existing quality suite already gates every push; deploys become
repeatable, audited and rollback-able by re-running the workflow at a prior
commit; no deploy-from-laptop dependency.

Pipeline (extends the existing CI job; manual dispatch first, then on main):

1. existing quality suite (unit, lint, coverage, e2e);
2. ssh with the secret key to the instance: git fetch + checkout, venv sync,
   migrations, systemd restart, `curl /healthz` smoke;
3. record release evidence in TASK_LOG.

Secrets live in GitHub repo secrets (never in git): OCI_HOST_1, OCI_HOST_2,
OCI_USER, OCI_SSH_KEY. The application `.env` is provisioned on the
instances directly (outside the repo), same keys as development.

## R2 bucket naming (resolved 2026-11-15)

Keep the default `aknja-digital-artifacts` bucket. Creating an additional
bucket later requires either the Cloudflare dashboard (R2 -> Create bucket)
or an API token with **Admin Read & Write** permission — object-scoped
tokens (Object Read & Write) cannot create buckets
(https://developers.cloudflare.com/r2/api/tokens).

## Inputs still missing (founder)

1. Re-share instance access: username, both public IPs, SSH private key —
   the earlier share did not reach the project workspace (verified absent
   from .env, upload/ and git history). Paste in chat, or drop the key at
   `upload/oci_key.pem` (*.pem is gitignored; plain files under upload/ are
   NOT ignored — never put secrets there as text).
2. Security list / NSG: allow inbound 22 (key-only auth), 80 and 443.
3. Optional: a domain name for automatic TLS (Caddy). Without one, use
   Cloudflare free proxy or Caddy on-demand TLS — decide at deploy time.
4. Confirm the role assignment (instance 1 = production) or override.

## Rollback

Redeploy the prior commit through the same workflow; restore SQLite from the
latest R2 backup per docs/22 if data rollback is required.
