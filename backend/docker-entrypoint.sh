#!/usr/bin/env sh
# Container entrypoint: migrate, seed the demo data on first run, then serve.
# A reviewer who runs `docker compose up` gets a working, populated app.
set -e

echo "Running migrations…"
ALEMBIC_DATABASE_URL="$SYNC_DATABASE_URL" alembic upgrade head

if [ "${SEED_ON_START:-true}" = "true" ]; then
  echo "Seeding demo data…"
  python -m scripts.seed || echo "Seed skipped or already applied."
fi

echo "Starting API…"
exec uvicorn incident_desk.main:app --host 0.0.0.0 --port 8000
