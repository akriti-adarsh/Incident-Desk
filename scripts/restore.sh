#!/usr/bin/env bash
# Restore the compose Postgres from a dump produced by backup.sh.
#
#   scripts/restore.sh <dump-file>
#
# Drops and recreates the target database, then restores. Refuses to run
# without an explicit confirmation, since it is destructive.
set -euo pipefail

FILE="${1:?usage: restore.sh <dump-file>}"
DB="${POSTGRES_DB:-incident_desk}"
USER="${POSTGRES_USER:-incident}"
SERVICE="${POSTGRES_SERVICE:-postgres}"

if [ ! -f "$FILE" ]; then
  echo "No such dump file: $FILE" >&2
  exit 1
fi

echo "This will DROP and recreate database '$DB' and restore from $FILE."
printf "Type the database name to confirm: "
read -r CONFIRM
if [ "$CONFIRM" != "$DB" ]; then
  echo "Confirmation did not match; aborting." >&2
  exit 1
fi

echo "Terminating connections and recreating '$DB'…"
docker compose exec -T "$SERVICE" psql -U "$USER" -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB' AND pid<>pg_backend_pid();"
docker compose exec -T "$SERVICE" psql -U "$USER" -d postgres -c "DROP DATABASE IF EXISTS $DB;"
docker compose exec -T "$SERVICE" psql -U "$USER" -d postgres -c "CREATE DATABASE $DB;"

echo "Restoring…"
docker compose exec -T "$SERVICE" pg_restore -U "$USER" -d "$DB" --no-owner < "$FILE"
echo "Restore complete."
