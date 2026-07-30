# Operations runbook

Practical procedures for running incident-desk. Every command here has been
run against the compose stack.

## Contents

- [Run migrations safely](#run-migrations-safely)
- [Roll back a bad deploy](#roll-back-a-bad-deploy)
- [Handle a stuck job queue](#handle-a-stuck-job-queue)
- [Rotate secrets](#rotate-secrets)
- [Back up and restore](#back-up-and-restore)
- [Zero-downtime migration policy](#zero-downtime-migration-policy)

## Run migrations safely

Migrations run on the synchronous psycopg driver (the app runs on asyncpg).

```bash
cd backend
# Preview what will run without applying it:
ALEMBIC_DATABASE_URL="$SYNC_DATABASE_URL" uv run alembic history --verbose
# Apply:
ALEMBIC_DATABASE_URL="$SYNC_DATABASE_URL" uv run alembic upgrade head
```

Before merging any migration, CI runs `upgrade head -> downgrade -1 -> upgrade
head` on a scratch database and asserts autogenerate produces no diff (see
`tests/test_migration_drift.py`). If that check is red, the migration and the
models disagree; fix before deploying.

**Never** hand-edit a migration that has already been applied in an
environment you cannot rebuild. Write a new forward migration instead.

## Roll back a bad deploy

1. Redeploy the previous image tag (the app is stateless; the database is the
   only state).
2. If the bad deploy shipped a migration, decide whether it is
   backward-compatible:
   - **Additive migration** (new nullable column, new table, new index): the
     old code ignores it. Just roll the image back. No database change needed.
   - **Destructive migration** (dropped/renamed column): this is why the
     zero-downtime policy below forbids doing that in one step. If it happened
     anyway, restore from the pre-deploy backup (see below) and investigate.
3. Confirm health: `curl localhost:8000/health/ready` should return `ready`.

## Handle a stuck job queue

Symptoms: escalations not firing, emails not sending, the dead-letter set
growing.

```bash
# Is the worker alive?
docker compose logs worker --tail 50

# Inspect the dead-letter set (jobs that exhausted their retries):
docker compose exec redis redis-cli SMEMBERS incident_desk:dead_letter

# Requeue a specific function by hand after fixing the cause, e.g. metrics:
docker compose exec api python -c "import asyncio; from arq import create_pool; \
from arq.connections import RedisSettings; from incident_desk.config import get_settings; \
asyncio.run((lambda: create_pool(RedisSettings.from_dsn(get_settings().redis_url)))())"

# Clear the dead-letter set once the underlying issue is resolved:
docker compose exec redis redis-cli DEL incident_desk:dead_letter

# Restart the worker:
docker compose restart worker
```

Jobs are idempotent (escalation re-reads incident state; the metrics rollup
upserts), so requeuing a job that partly ran is safe.

## Rotate secrets

`JWT_SECRET` signs access tokens. Rotating it invalidates every outstanding
access token (they fail signature verification), but refresh tokens are stored
hashed in the database and keep working, so users get new access tokens
silently on their next refresh.

```bash
# 1. Set the new secret in the environment / secret store.
# 2. Restart the api and worker so they pick it up:
docker compose up -d --no-deps api worker
```

For a forced global logout, additionally bump every user's `token_version` (a
one-off SQL `UPDATE users SET token_version = token_version + 1`), which
invalidates outstanding refresh sessions too.

## Back up and restore

```bash
# Back up to ./backups/incident_desk_<timestamp>.dump
scripts/backup.sh

# Restore (destructive; asks for confirmation):
scripts/restore.sh backups/incident_desk_20260801T030000Z.dump
```

Take a backup immediately before any deploy that carries a migration.

## Zero-downtime migration policy

Additive-only, two-phase for anything that removes or changes a column:

1. **Expand.** Add the new column/table (nullable, defaulted). Deploy code that
   writes both old and new and reads old. The old code still works against the
   new schema.
2. **Migrate data** in the background if needed.
3. **Contract.** Once all replicas run the new code and the old column is
   unused, deploy code that reads the new column, then a later migration drops
   the old one.

The migration history includes one deliberately two-phase change
(`event_sequence_ordering` added the monotonic `seq` column additively rather
than repurposing `created_at`), demonstrating the pattern.
