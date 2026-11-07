#!/usr/bin/env sh
set -eu
umask 077

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "Missing .env; run this script from a configured deployment." >&2
  exit 1
fi

BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"

DB_BACKUP="$BACKUP_DIR/postgres-$STAMP.sql.gz"
STORAGE_BACKUP="$BACKUP_DIR/storage-$STAMP.tar.gz"
TMP_SQL="$BACKUP_DIR/.postgres-$STAMP.sql"
TMP_STORAGE="$BACKUP_DIR/.storage-$STAMP.tar.gz"
cleanup() {
  rm -f "$TMP_SQL" "$TMP_SQL.gz" "$TMP_STORAGE"
}
trap cleanup EXIT HUP INT TERM

# Avoid a pipeline that could hide pg_dump errors behind a successful gzip exit.
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$TMP_SQL"
gzip -9 "$TMP_SQL"
mv "$TMP_SQL.gz" "$DB_BACKUP"

# Preserve originals and generated workbooks together with the database dump.
tar -czf "$TMP_STORAGE" storage/
mv "$TMP_STORAGE" "$STORAGE_BACKUP"

echo "Backup completed:"
echo "  $DB_BACKUP"
echo "  $STORAGE_BACKUP"
