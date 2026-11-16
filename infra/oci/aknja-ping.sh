#!/bin/bash
# Quota snapshot refresh for the free-provider pool (T-026, docs/33).
#
# Quota snapshots older than 6h fail-closed EVERY provider (SNAPSHOT_STALE_AFTER),
# so the pool must be re-observed on a schedule. Each llm-ping first re-records
# the product's snapshot (same-day usage carried over) and then makes one real
# governed call — a failing ping still refreshes the snapshot, so a provider in
# a degraded upstream window stays quota-eligible instead of going stale.
#
# Installed as a systemd timer (every 4h) by aknja-deploy.sh.
set -uo pipefail
cd /home/ubuntu/aknja-digital
PY=.venv/bin/python
declare -A STATUS

ping_one() {  # provider task [prompt]
  local provider="$1" task="$2" prompt="${3:-}"
  local args=(--provider "$provider" --task "$task")
  if [ -n "$prompt" ]; then args+=(--prompt "$prompt"); fi
  if $PY -m app.cli llm-ping "${args[@]}" >/dev/null 2>&1; then
    STATUS[$provider]=OK
  else
    STATUS[$provider]=SLOW
  fi
}

# translation needs the exact benchmark instruction shape the worker parses
ML_PROMPT='താഴെയുള്ള ഇംഗ്ലീഷ് വാക്യം മലയാളത്തിലേക്ക് വിവർത്തനം ചെയ്യുക. ബ്രാൻഡ് പേരുകൾ അതേപടി നിലനിർത്തുക. വിവർത്തനം മാത്രം ഔട്ട്പുട്ട് ചെയ്യുക.

വാക്യം: The bakery accepts orders until 8 pm.'

ping_one groq code_review
ping_one gemini summarization
ping_one openrouter classification
ping_one indictrans2 translation "$ML_PROMPT"

for p in groq gemini openrouter indictrans2; do
  echo "aknja-ping: $p ${STATUS[$p]:-UNKNOWN}"
done
# snapshots refreshed regardless of upstream health — never fail the unit
exit 0
