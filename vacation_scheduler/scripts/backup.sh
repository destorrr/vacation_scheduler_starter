#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "Missing .env; run this script from a configured deployment." >&2
  exit 1
fi

BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"

# The database container supplies its own POSTGRES_USER and POSTGRES_DB.
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | gzip -9 > "$BACKUP_DIR/postgres-$STAMP.sql.gz"

# Preserve originals and generated workbooks together with the database dump.
tar -czf "$BACKUP_DIR/storage-$STAMP.tar.gz" storage/

echo "Backup completed:"
echo "  $BACKUP_DIR/postgres-$STAMP.sql.gz"
echo "  $BACKUP_DIR/storage-$STAMP.tar.gz"
