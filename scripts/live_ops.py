#!/usr/bin/env python3
"""Run app CLI commands against a real local PostgreSQL (pgserver cluster).

Boots/reuses the gitignored cluster pgdata-aknja-live inside the repo,
creates the aknja_live database (--fresh drops and recreates it), then runs
each given CLI command with DATABASE_URL pointed at it. Secrets (Telegram
token, LLM keys, R2 credentials) come from the gitignored .env, which
pydantic-settings loads relative to the repo root — this script never
prints them.

Usage:
  python scripts/live_ops.py --fresh -- init-db seed import-taxonomy \\
         register-provider-candidates
  python scripts/live_ops.py -- send-test-notification
  python scripts/live_ops.py -- llm-ping --provider gemini --task qa_review
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PGDATA = str(REPO / "pgdata-aknja-live")
DB_NAME = "aknja_live"
VENV_PY = REPO / ".venv" / "bin" / "python"


def database_url(fresh: bool) -> str:
    import pgserver
    import psycopg

    server = pgserver.get_server(PGDATA)
    uri = server.get_uri()  # postgresql://postgres:@/postgres?host=...
    m = re.match(r"postgresql://([^:]*):([^@]*)@/([^?]+)\?host=(.+)", uri)
    if m is None:
        raise RuntimeError(f"unexpected pgserver uri shape: {uri!r}")
    user, password, _dbname, host = m.groups()
    with psycopg.connect(uri, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)
        ).fetchone()
        if not exists or fresh:
            if exists:
                conn.execute(f"DROP DATABASE {DB_NAME} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {DB_NAME}")
    return f"postgresql+psycopg://{user}:{password}@/{DB_NAME}?host={host}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fresh", action="store_true",
                    help="drop and recreate the aknja_live database first")
    ap.add_argument("commands", nargs=argparse.REMAINDER,
                    help="CLI commands after -- (each runs as: python -m app.cli <cmd...>)")
    args = ap.parse_args()
    cmds = [c for c in args.commands if c != "--"]
    if not cmds:
        ap.print_help()
        return 2

    url = database_url(fresh=args.fresh)
    print(f"[live_ops] cluster ready, database {DB_NAME} ({'fresh' if args.fresh else 'reused'})")

    env = dict(os.environ)
    env["DATABASE_URL"] = url  # real env var wins over .env (pydantic precedence)
    rc_total = 0
    for cmd in cmds:
        argv = [str(VENV_PY), "-m", "app.cli"] + shlex.split(cmd)
        print(f"\n[live_ops] $ python -m app.cli {cmd}")
        rc = subprocess.run(argv, check=False, cwd=str(REPO), env=env).returncode
        rc_total |= rc
        if rc != 0:
            print(f"[live_ops] FAILED (exit {rc}): {cmd}")
            break
    return rc_total


if __name__ == "__main__":
    sys.exit(main())
