#!/usr/bin/env bash
# Back up the compose Postgres to a timestamped custom-format dump.
#
#   scripts/backup.sh [output-dir]
#
# Uses pg_dump inside the running postgres container, so it needs no local
# Postgres client. The custom format (-Fc) is compressed and restorable with
# pg_restore (see restore.sh).
set -euo pipefail

OUT_DIR="${1:-./backups}"
DB="${POSTGRES_DB:-incident_desk}"
USER="${POSTGRES_USER:-incident}"
SERVICE="${POSTGRES_SERVICE:-postgres}"

mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$OUT_DIR/incident_desk_${STAMP}.dump"

echo "Backing up database '$DB' -> $FILE"
docker compose exec -T "$SERVICE" pg_dump -U "$USER" -Fc "$DB" > "$FILE"

SIZE="$(wc -c < "$FILE")"
echo "Done. Wrote $SIZE bytes to $FILE"
