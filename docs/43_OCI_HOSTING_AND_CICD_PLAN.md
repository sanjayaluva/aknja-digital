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

## Deployment record — 2026-11-15 (instance 1 = production, LIVE)

Verified facts (first SSH login):

- instance 1 `ubuntu@144.24.102.22` (aknja.pp.ua): aarch64, Ubuntu 22.04.5,
  kernel 6.8.0-1049-oracle, Python 3.10 system.
- instance 2 `ubuntu@80.225.208.59`: aarch64, Ubuntu 24.04.5,
  kernel 6.17.0-1011-oracle, Python 3.12.3 system.
- Both: 1 OCPU, in-OS iptables default-REJECT except 22 (OCI Ubuntu image
  default) — rules for 80/443 inserted and persisted on instance 1.
- SSH from the dev sandbox has no openssh client; deploys use paramiko with
  the founder's key (kept at gitignored `upload/oci_key.pem`).

Production stack deployed on instance 1 (phased script
`scripts/t021d_deploy_prod.py`, artifacts in `infra/oci/`):

- PostgreSQL 14 (role/db `aknja`, scram, localhost only) + alembic x5
  migrations applied.
- uv-managed CPython 3.12.16 (aarch64) + `uv sync --frozen --no-dev`
  (all wheels available for linux-aarch64).
- `aknja.service`: uvicorn on 127.0.0.1:8000 (systemd, Restart=always).
- Caddy reverse proxy, automatic Let's Encrypt TLS for aknja.pp.ua;
  HTTP 80 → 308 → HTTPS.
- `aknja-notifications.timer` (outbox every 5 min) and
  `aknja-backup.timer` (02:30 UTC: create → push → prune, offsite to R2).
- Prod `.env` generated from the dev `.env` with APP_ENV=production, fresh
  DATABASE_URL/SECRET_KEY; recovery copy at gitignored `.env.production`.

Verification: `https://aknja.pp.ua/healthz` → HTTP 200
`{"status":"ok","version":"0.1.0","env":"production"}`, TLS verify 0,
external path (OCI security list 80/443) green.

Incident during deploy (fixed same day): the .env builder re-parsed the
generated DATABASE_URL with `split(':')[-1]`, corrupting the DB password on
re-run to "5432/aknja" → alembic auth failure. Fixed to parse between
`aknja:` and `@` with sanity guards, plus an idempotent `ALTER ROLE` that
always syncs the role password to `.env.production`; credentials regenerated
and migration re-run clean.

R2 permissions check (same day): the founder elevated the EXISTING R2 token
(fingerprints identical to `.env`) — ListBuckets 200, test bucket
create/visible/delete round-trip CONFIRMED. Bucket-creation rights work;
`.env` unchanged. Default bucket `aknja-digital-artifacts` stays.

Instance 2 remains clean — reserved for staging + restore-drill target +
IndicTrans2 translation worker (docs/34 §3). The GitHub-Actions-over-SSH
deploy workflow (this deploy ran via the persisted script) is the next
increment; `infra/oci/` + the phased script are the reproducible base.

## Instance-2 + translation worker record — 2026-11-15 (T-023)

- staging app: PostgreSQL (aknja_staging), uv CPython 3.12.16 aarch64,
  `uv sync --frozen --no-dev`, alembic x5, super-admin + seed (49/10/5) +
  taxonomy (224 services); uvicorn 127.0.0.1:8000 (aknja.service), SSH
  tunnel access only (`ssh -L 8080:localhost:8000 ubuntu@80.225.208.59`).
- translation worker: IndicTrans2-dist-200M both directions (MIT, HF
  gated:auto — access granted to the founder account), OpenAI-compatible
  shim at 127.0.0.1:8001 (infra/oci/worker/). Strategy validated 8/8
  against the app's benchmark evaluator: Devanagari script unification
  handled by post/pre conversion; brand terms preserved via startup-
  calibrated stem restore (en→X) and glossary injection (X→en); 400 on
  non-translation prompts. transformers PINNED to 4.38.2 (5.x removed
  transformers.onnx which the custom code imports).
- reverse SSH tunnel (inst2 → inst1:127.0.0.1:8001) — no OCI security-list
  change needed; dedicated ed25519 key on inst2, restricted to
  port-forwarding on inst1 (`restrict,port-forwarding`).
- CI/CD LIVE: `.github/workflows/deploy.yml` (workflow_dispatch →
  restricted deploy key → `aknja-deploy.sh` wrapper accepting ONLY a
  40-char sha → uv sync + alembic + restart + healthz, then external
  https://aknja.pp.ua/healthz smoke). Deployed 1b6c8b8 through the full
  GitHub path (run: completed success). Wrapper source in infra/oci/.
- DR evidence: prod offsite restore drill PASSED (counts/schema/
  audit_chain, isolated scratch DB; `aknja` role granted CREATEDB for
  drills) + instance-2 cross-host R2 pull with sha256 match.
