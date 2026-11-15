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
# uv (https://docs.astral.sh/uv/) resolves the committed uv.lock bit-for-bit:
uv sync --frozen --all-extras
# without uv: python -m venv .venv && source .venv/bin/activate
#             pip install -e ".[dev]"
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
pytest -q                # 160 tests against real PostgreSQL (see conftest notes)
ruff check app tests     # zero errors enforced in CI
mypy app                 # advisory; strictness still being tightened
```

The test suite requires PostgreSQL. It reads `AKNJA_TEST_DATABASE_URL` if set;
otherwise it provisions a self-contained PostgreSQL (pgserver, cluster dir
`pgdata-aknja/` inside the repo, gitignored). CI provisions `postgres:16` as a
service container and runs the unit/integration job with `-m "not e2e"`.

**E2E (Playwright):** `tests/e2e/` starts a real uvicorn server against a
scratch database. Without `AKNJA_E2E_DATABASE_URL` it uses a second pgserver
cluster (`pgdata-aknja-e2e/`); with it set (CI) it runs against that URL
directly. `AKNJA_E2E=skip` disables the layer. Install browsers once with
`playwright install chromium`.

**Visual baselines** (`tests/e2e/test_visual.py`) compare full-page PNGs with a
0.2% pixel tolerance. They are tied to the font stack of the machine that
generated them, so CI runs only the functional E2E flows; baselines are a
local gate. If a diff exceeds tolerance: verify it is drift, not a regression
(`python infra/baseline_verify.py --old <old>.png --new <new>.png`), then
regenerate with `AKNJA_E2E_UPDATE_BASELINES=1 pytest -q tests/e2e/test_visual.py`.

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

The pool includes the doc-sourced services (SRS §7/§8.4, docs/33, docs/14 —
Neon, Supabase, R2, Tigris, B2, OCI, Gemini, Groq, Cerebras, OpenRouter,
Mistral, HF, Brevo, Resend, MailerSend, Upstash, Azure Speech, Sarvam,
OCI A1, GitHub Actions, Kaggle, **Colab, Modal, HF Spaces, Cloudflare
Pages, Jina**) plus the web-researched watchlist of `docs/34_FREE_SERVICE_CANDIDATE_WATCHLIST.md`
(Workers AI, GitHub Models, UptimeRobot, Better Stack, Brave Search, Tavily,
Redis Cloud — researched 2026-11-14, provenance recorded per entry).

## 10. LLM inference layer and llm-ping

`app/modules/ai/inference.py` is the provider-neutral inference layer
(v5.3.2 §5C): 7 task profiles (classification, translation, summarization,
requirements, code_review, proposal_draft, qa_review), HTTP adapters for
Groq, GitHub Models, Gemini and Cloudflare Workers AI (OpenAI-compatible or
native REST, no vendor SDKs), per-attempt quota admission through the
zero-cost engine, audited failover on 429/5xx to the next eligible free
provider, and a fail-closed PENDING_MANUAL result when no verified provider
remains. Every attempt is logged in `llm_call_logs` with a prompt hash only.

The governed entry point is the `llm.generate` tool through the Tool
Gateway — PUBLIC/INTERNAL data only; CONFIDENTIAL and RESTRICTED data can
never egress to a third-party model.

```bash
# Test a verified provider with one real completion (v5.3.2 §8 action):
python -m app.cli llm-ping --provider groq
python -m app.cli llm-ping --provider gemini --model gemini-3.8-flash \
  --prompt "Reply with exactly: PONG"
```

Requires: `AI_PROVIDER_ENABLED=true` in `.env` (master switch), the
provider key in settings, and the provider verified+enabled in the registry
(`verify-provider`). Unverified providers fail closed with guidance.

## 11. Development round protocol

Every development request is one round and must update, before it counts as
done: (1) code + tests + lint, (2) `.aknja/tasks/TASK_LOG.md` record with
verification evidence, (3) `.aknja/memory/` episodic summary with provenance,
(4) every numbered doc the round touches (backlog docs/32, roadmap docs/04,
this runbook, docs/33/34 on provider changes, SRS erratum on invalidated
assumptions), (5) `.aknja/STATUS.md` evidence table + truthful "Not claimed"
list, (6) one commit + push whose hash lands in the task record.
Full protocol: `.aknja/README.md` § Development round protocol.

## 12. Telegram notification outbox (T-006)

Env (unset = channel unconfigured; rows queue PENDING, nothing is lost):

    export TELEGRAM_BOT_TOKEN="123456:ABC..."   # from @BotFather
    export TELEGRAM_ADMIN_CHAT_ID="424242"     # message the bot once, then use the chat id

Test the channel, then drain due notifications (send/retry per docs/39):

    python -m app.cli send-test-notification --language en
    python -m app.cli process-notifications

Hooks that enqueue: approval.requested, quota.hard_stop (per product per
UTC day), run.blocked (AI run parked for founder review). Language follows
the `default_admin_language` setting (ml|en).

## 13. LLM provider quality benchmark (v5.3.2 §6, T-008)

Benchmark one verified provider across all seven task profiles and four
languages (36 scenarios; each consumes one quota unit):

    python -m app.cli run-llm-benchmark --provider groq
    python -m app.cli run-llm-benchmark --provider groq --tasks classification,translation --languages ml,en

Exit 0 only if every selected task meets its quality floor. A FAILED run
records a durable benchmark row and the inference layer then skips the
provider for the failed tasks until a passing re-run (fresh window: 30
days). Failed runs also enqueue a founder Telegram alert.
