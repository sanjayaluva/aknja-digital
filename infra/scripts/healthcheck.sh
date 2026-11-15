#!/usr/bin/env bash
set -euo pipefail
URL="${1:?usage: healthcheck.sh https://host/health/ready}"
curl --fail --silent --show-error --max-time 10 "$URL"
