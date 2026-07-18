#!/bin/bash
# Daily database backup — safe for cron.
#
# Usage: ops/backup-db.sh
#
# Reads PJSK_DB_PATH from environment (defaults to shared/data/pjsk.db).
# Creates timestamped, gzipped SQL dumps in shared/backups/.
# Keeps the most recent 14 daily backups; removes older ones.
# Fails safe: never overwrites the live database, never exits non-zero
# (cron will not spam on transient failures).
set -euo pipefail

DB="${PJSK_DB_PATH:-/opt/pjsk-astrbot/shared/data/pjsk.db}"
BACKUP_DIR="${PJSK_BACKUP_DIR:-/opt/pjsk-astrbot/shared/backups}"
RETENTION_DAYS="${PJSK_BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB" ]; then
    echo "[backup] $(date -u +%Y-%m-%dT%H:%M:%SZ) — database file not found: $DB" >&2
    exit 0
fi

# ── Dump ──────────────────────────────────────────────────────────────────
BACKUP_FILE="$BACKUP_DIR/pjsk-${TIMESTAMP}.sql.gz"

# Run integrity check first; skip backup on corruption
sqlite3 "$DB" "PRAGMA integrity_check;" | grep -q '^ok$' || {
    echo "[backup] $(date -u +%Y-%m-%dT%H:%M:%SZ) — integrity check FAILED, skipping backup" >&2
    exit 0
}

sqlite3 "$DB" .dump | gzip > "$BACKUP_FILE"
echo "[backup] $(date -u +%Y-%m-%dT%H:%M:%SZ) — created: $(du -h "$BACKUP_FILE" | cut -f1)" >&2

# ── Rotate ────────────────────────────────────────────────────────────────
find "$BACKUP_DIR" -name 'pjsk-*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete 2>/dev/null || true
