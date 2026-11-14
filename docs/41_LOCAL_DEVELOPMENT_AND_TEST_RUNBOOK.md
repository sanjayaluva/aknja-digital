# Local Development and Test Runbook

Verified end-to-end on a clean checkout with Python 3.12 and PostgreSQL 16.
CI (`.github/workflows/ci.yml`) runs the identical sequence on every push/PR.

## 1. Prerequisites

- Python 3.12+
- PostgreSQL 16 (Docker Compose service, local install, or any managed instance)
- No external AI/provider keys are required — core startup is provider-free (SRS §14).

## 2. Bootstrap

```bash
git clone https://github.com/sanjayaluva/aknja-digital.git && cd aknja-digital
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                     # then edit SECRET_KEY + DATABASE_URL
```

## 3. Database

**Option A — Docker Compose (recommended):**

```bash
docker compose up -d db
# DATABASE_URL=postgresql+psycopg://aknja:local-only-change-me@localhost:5432/aknja
```

**Option B — existing PostgreSQL:** create an empty database and point
`DATABASE_URL` at it (psycopg 3 URL).

Apply migrations and bootstrap the platform:

```bash
alembic upgrade head
python -m app.cli create-super-admin --email founder@aknja.pp.ua   # prompts for password
python -m app.cli seed                # 43 system settings + 10 capabilities + 4 tools
python -m app.cli import-taxonomy     # 19 families / 76 subcategories / 224 services
python -m app.cli verify-install      # post-install evidence (all checks must PASS)
```

## 4. Run

```bash
uvicorn app.main:app --reload
# UI:      http://127.0.0.1:8000/admin   (internal roles)
# Portal:  http://127.0.0.1:8000/portal  (CLIENT_OWNER / CLIENT_MEMBER)
# API docs:http://127.0.0.1:8000/api/docs
# Health:  /health/live  /health/ready
```

## 5. Test, lint, type checks

```bash
pytest -q                # 80 tests against real PostgreSQL (see conftest notes)
ruff check app tests     # zero errors enforced in CI
mypy app                 # advisory; strictness still being tightened
```

The test suite requires PostgreSQL. It reads `AKNJA_TEST_DATABASE_URL` if set;
otherwise it provisions a self-contained PostgreSQL (pgserver) or uses
`DATABASE_URL`. CI provisions `postgres:16` as a service container.

## 6. Docker Compose full stack

```bash
docker compose up -d --build                      # db + api (migrations run in entrypoint)
docker compose --profile tools run --rm bootstrap # seed + taxonomy + verify
```

## 7. Common operations

| Task | Command |
| --- | --- |
| Emergency stop (HARD) | `POST /api/v1/emergency-stop {"state":"HARD","reason":"..."}` (Super Admin only) |
| Audit chain verification | `GET /api/v1/audit-events/verify` |
| Export OpenAPI | `GET /api/openapi.json` |
| New migration | `alembic revision --autogenerate -m "..."` |

## 8. Troubleshooting

- **401 on every request after login:** `APP_ENV` is `staging`/`production`, so
  cookies are `Secure` — use HTTPS or set `APP_ENV=local` for plain-HTTP dev.
- **`audit_events is append-only` errors:** intentional. Founder-only corrections
  require `SET aknja.audit_admin = 'on'` in the same transaction.
- **Providers never admitted:** expected. Only `FREE_VERIFIED` + enabled
  accounts with fresh snapshots are eligible; everything else fails closed.

## 9. Free-tier provider pool: registration and verification

The documented candidate pool (docs/33, `docs/source_provider_pools_v5.3.2.md`
§5, SRS §9) covers eight categories: relational DB (Neon/Supabase/OCI),
object storage (R2/Tigris/B2/OCI), AI/LLM (Gemini/Groq/Cerebras/OpenRouter/
Mistral/HF), transactional email (Brevo/Resend/MailerSend), cache/queue
(Upstash), speech (Azure F0/Sarvam), monitoring and hosting/compute
(OCI A1/GitHub Actions/Kaggle). `.env.example` lists every key slot; keys
alone enable nothing.

```bash
# 1) Seed the candidate pool (idempotent, all FREE_UNVERIFIED + disabled):
python -m app.cli register-provider-candidates

# 2) For each provider you actually own, verify it in the provider console
#    (plan, quota, reset window, privacy, commercial-use terms — docs/33
#    worksheet) and record the evidence:
python -m app.cli verify-provider \
  --provider groq --product-key "groq free tier" \
  --allowance 14400 --metric requests \
  --docs-url "https://console.groq.com/docs/rate-limits" \
  --evidence "verified in console <date> by <reviewer>" \
  --commercial-use-ok --enable
```

Until step 2 runs for a provider, the quota engine fails closed on it —
that is the intended zero-cost behaviour, not a bug. Verification is audited
(`provider.verified`) and re-running `register-provider-candidates` never
resets an already-verified account. Privacy note: the free Gemini tier uses
content for training — confidential client data must never be routed there
(v5.3.2 §5C); the registry metadata carries this warning.
