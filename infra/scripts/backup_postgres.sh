#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"
: "${BACKUP_DIR:?BACKUP_DIR is required}"
mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
pg_dump "$DATABASE_URL" --format=custom --no-owner --file "$BACKUP_DIR/aknja-$STAMP.dump"
sha256sum "$BACKUP_DIR/aknja-$STAMP.dump" > "$BACKUP_DIR/aknja-$STAMP.dump.sha256"
echo "Created backup: $BACKUP_DIR/aknja-$STAMP.dump"
