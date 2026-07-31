"""Capture EXPLAIN ANALYZE for the incident-list query, before and after the
composite index, on a realistically sized dataset.

Builds a scratch database, bulk-loads ~50k incidents into one organisation,
then runs the exact keyset query the list endpoint issues, first without and
then with ``ix_incidents_org_created_id``. Prints both plans so the improvement
is measured, not asserted. The captured output lives in docs/performance.md.

Run: ``uv run python -m loadtest.explain_index``.
"""

import uuid

import psycopg

from incident_desk.config import get_settings

ROWS = 50_000

LIST_QUERY = """
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT id, title, severity, status, created_at
FROM incidents
WHERE org_id = %(org_id)s
ORDER BY created_at DESC, id DESC
LIMIT 25;
"""


def _admin_dsn(dsn: str, database: str) -> str:
    from sqlalchemy import make_url

    return (
        make_url(dsn)
        .set(drivername="postgresql", database=database)
        .render_as_string(hide_password=False)
    )


def main() -> None:
    settings = get_settings()
    base = settings.sync_database_url.replace("postgresql+psycopg", "postgresql")
    from sqlalchemy import make_url

    scratch = f"perf_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(_admin_dsn(base, "postgres"), autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{scratch}"')

    scratch_dsn = make_url(base).set(database=scratch).render_as_string(hide_password=False)
    try:
        with psycopg.connect(scratch_dsn, autocommit=True) as conn:
            org_id = uuid.uuid4()
            service_id = uuid.uuid4()
            user_id = uuid.uuid4()
            # Minimal schema for the query under test (no FKs; this is a
            # throwaway database used only to measure the plan).
            conn.execute(
                """
                CREATE TABLE incidents (
                    id uuid PRIMARY KEY,
                    org_id uuid NOT NULL,
                    service_id uuid NOT NULL,
                    reported_by uuid NOT NULL,
                    sequence_number int NOT NULL,
                    title text NOT NULL,
                    severity text NOT NULL,
                    status text NOT NULL DEFAULT 'open',
                    created_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            # A handful of other orgs so org_id is selective, plus the target.
            print(f"Loading {ROWS} incidents into one org ...")
            with (
                conn.cursor() as cur,
                cur.copy(
                    "COPY incidents (id, org_id, service_id, reported_by, "
                    "sequence_number, title, severity, created_at) FROM STDIN"
                ) as copy,
            ):
                for i in range(ROWS):
                    other = org_id if i % 3 else uuid.uuid4()
                    copy.write_row(
                        (
                            uuid.uuid4(),
                            other,
                            service_id,
                            user_id,
                            i,
                            f"Incident {i}",
                            "sev3",
                            "2026-01-01 00:00:00+00",
                        )
                    )
            # Fix created_at spread (COPY above kept it constant); jitter it so
            # the ORDER BY has real work to do.
            conn.execute(
                "UPDATE incidents SET created_at = now() - (random() * interval '90 days')"
            )
            conn.execute("ANALYZE incidents")

            print("\n=== BEFORE: no composite index ===")
            for row in conn.execute(LIST_QUERY, {"org_id": org_id}):
                print(row[0])

            conn.execute(
                "CREATE INDEX ix_incidents_org_created_id ON incidents (org_id, created_at, id)"
            )
            conn.execute("ANALYZE incidents")

            print("\n=== AFTER: with ix_incidents_org_created_id ===")
            for row in conn.execute(LIST_QUERY, {"org_id": org_id}):
                print(row[0])
    finally:
        with psycopg.connect(_admin_dsn(base, "postgres"), autocommit=True) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                (scratch,),
            )
            conn.execute(f'DROP DATABASE "{scratch}"')


if __name__ == "__main__":
    main()
