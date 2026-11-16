#!/usr/bin/env python3
"""Build the gitignored .env from the founder's uploaded credential sheet.

Reads /home/z/my-project/upload/aknja-credentials.txt (two formats: KEY=value
lines and "Label : value" lines, plus a `modal token set` command line) and
writes <repo>/.env with the variable names the platform expects
(docs/41 §5, .env.example). Values are never printed; the script only lists
the variable NAMES it wrote. .env is chmod 600 and gitignored — never commit.

Usage: python scripts/build_env.py [--force]
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHEET = Path("/home/z/my-project/upload/aknja-credentials.txt")
ENV_OUT = REPO / ".env"

# ---- parse the sheet -------------------------------------------------------

kv: dict[str, str] = {}
for line in SHEET.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    m = re.match(r"^([A-Z][A-Z0-9_]+)\s*=\s*(\S.*)$", line)
    if m and not line.startswith("#"):
        kv[m.group(1)] = m.group(2).strip()
    lm = re.match(r"^(Account ID|S3 API|Access Key ID|Secret Access Key|"
                  r"Token value|Token ID|Token Secret|Huggingface Full Access Token)"
                  r"\s*:\s*(\S.*)$", line)
    if lm:
        kv[lm.group(1)] = lm.group(2).strip()

# `modal token set --token-id ak-... --token-secret as-...`
mset = re.search(r"modal token set --token-id (\S+) --token-secret (\S+)",
                 SHEET.read_text(encoding="utf-8"))
if mset:
    kv["MODAL_TOKEN_ID"], kv["MODAL_TOKEN_SECRET"] = mset.group(1), mset.group(2)


def need(*names: str) -> str:
    """First non-empty value among the given sheet keys, else ''."""
    for n in names:
        v = kv.get(n, "").strip().strip('"').strip("'")
        if v:
            return v
    return ""


# ---- map to platform slots --------------------------------------------------

gemini_pool = ",".join(x for x in (need("GEMINI_API_KEY"), need("GEMINI_API_KEY_BACKUP")) if x)
account_id = need("CLOUDFLARE_ACCOUNT_ID", "Account ID")
s3_api = need("S3_API", "S3 API") or (f"https://{account_id}.r2.cloudflarestorage.com" if account_id else "")

mapped: list[tuple[str, str]] = [
    # (env name, value)
    ("APP_ENV", "local"),
    ("APP_NAME", "Aknja Digital"),
    ("SECRET_KEY", secrets.token_urlsafe(48)),
    # DATABASE_URL is overridden per-run by scripts/live_ops.py (pgserver).
    ("DATABASE_URL", "postgresql+psycopg://aknja:aknja_local_only@localhost:5432/aknja"),
    ("LOG_LEVEL", "INFO"),
    ("ZERO_COST_MODE", "true"),
    ("MAX_APPROVED_MONTHLY_SPEND_MINOR", "0"),
    ("PAID_FALLBACK_ENABLED", "false"),
    ("HARD_STOP_THRESHOLD_PCT", "95.0"),
    # --- AI_LLM layer-1 pool (keys alone enable nothing — registry gate) ---
    ("GEMINI_API_KEYS", gemini_pool),
    ("GROQ_API_KEYS", need("GROQ_API_KEY")),
    ("CEREBRAS_API_KEY", need("CEREBRAS_API_KEY")),
    ("OPENROUTER_API_KEY", need("OPENROUTER_API_KEY")),
    ("MISTRAL_API_KEY", need("MISTRAL_API_KEY")),
    ("HF_TOKEN", need("HUGGINGFACE_TOKEN", "Huggingface Full Access Token")),
    # --- Telegram control plane ---
    ("TELEGRAM_BOT_TOKEN", need("TELEGRAM_BOT_TOKEN")),
    # founder sheet name; config accepts it via alias (tests/test_config_env.py)
    ("TELEGRAM_FOUNDER_CHAT_ID", need("TELEGRAM_FOUNDER_CHAT_ID")),
    # --- Cloudflare R2 object storage (S3-compatible offsite backups) ---
    ("OBJECT_STORAGE_ENDPOINT", s3_api),
    ("OBJECT_STORAGE_BUCKET", need("CLOUDFLARE_R2_BUCKET_NAME")),
    ("OBJECT_STORAGE_ACCESS_KEY_ID", need("CLOUDFLARE_R2_ACCESS_KEY_ID", "Access Key ID")),
    ("OBJECT_STORAGE_SECRET_ACCESS_KEY", need("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "Secret Access Key")),
    ("R2_ACCOUNT_ID", account_id),
    # --- Modal (staging/compute offload candidate) ---
    ("MODAL_TOKEN_ID", need("MODAL_TOKEN_ID", "Token ID")),
    ("MODAL_TOKEN_SECRET", need("MODAL_TOKEN_SECRET", "Token Secret")),
]

header = """\
# ==============================================================================
# Aknja Digital — LOCAL runtime environment (generated, NEVER commit).
# Source: founder credential sheet 2026-11-15 + scripts/build_env.py.
# Keys alone enable nothing: providers activate only via the audited
# verify-provider registry step (docs/41 §9, SRS §14).
# ==============================================================================
"""

# ---- write -------------------------------------------------------------------

ap = argparse.ArgumentParser()
ap.add_argument("--force", action="store_true", help="overwrite an existing .env")
args = ap.parse_args()
if ENV_OUT.exists() and not args.force:
    print(f"refusing to overwrite {ENV_OUT} (use --force)")
    sys.exit(2)

filled = [f"{name}={value}" for name, value in mapped if value]
ENV_OUT.write_text(header + "\n".join(filled) + "\n", encoding="utf-8")
ENV_OUT.chmod(0o600)
print(f"wrote {ENV_OUT} ({ENV_OUT.stat().st_size} bytes, mode 600) with slots:")
print("  " + ", ".join(name for name, _ in mapped if name not in ("SECRET_KEY",)))
empty = [name for name, value in mapped if not value and name not in ("APP_ENV", "APP_NAME", "DATABASE_URL", "LOG_LEVEL", "ZERO_COST_MODE", "MAX_APPROVED_MONTHLY_SPEND_MINOR", "PAID_FALLBACK_ENABLED", "HARD_STOP_THRESHOLD_PCT")]
if empty:
    print("empty (not written): " + ", ".join(empty))
