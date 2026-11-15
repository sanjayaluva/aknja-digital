#!/bin/bash
# Restricted deploy entrypoint (command= in authorized_keys, T-023 docs/43).
# Installed at /home/ubuntu/aknja-deploy.sh on instance-1; the GitHub Actions
# deploy workflow (and only it) holds the matching key. Only argument: a
# 40-char commit SHA — no other command can run with this key.
set -euo pipefail
SHA="${SSH_ORIGINAL_COMMAND:-}"
if [[ ! "$SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "deploy: expected a 40-char commit sha, got: $SHA" >&2
  exit 1
fi
cd /home/ubuntu/aknja-digital
export PATH="$HOME/.local/bin:$PATH"
git fetch origin main
git checkout -f main
git reset --hard "$SHA"
uv sync --frozen --python 3.12 --no-dev
.venv/bin/alembic upgrade head
sudo systemctl restart aknja
# app boot takes a few seconds; retry the local health check (curl exit 7
# means "not listening yet" — race observed 2026-11-15)
for i in $(seq 1 15); do
  if curl -sf -m 5 http://127.0.0.1:8000/healthz; then
    echo
    echo "deploy: $SHA live"
    exit 0
  fi
  sleep 2
done
echo "deploy: $SHA deployed but healthz never came up" >&2
exit 1
