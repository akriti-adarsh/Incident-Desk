"""on-call shift overlap exclusion

Revision ID: 325e2ff810a8
Revises: e9e5ac43f16d
Create Date: 2026-07-30 11:11:45.140712

Two shifts on the same schedule must never overlap in time. Enforced at the
database, not in application code, so no code path (bulk import, seed script,
future endpoint) can create an overlap. ``EXCLUDE USING gist`` needs the
``btree_gist`` extension for the scalar ``schedule_id WITH =`` part, so the
extension is created in this same migration and a fresh database migrates
cleanly from zero.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "325e2ff810a8"
down_revision: str | None = "e9e5ac43f16d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ex_on_call_shifts_no_overlap"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        f"""
        ALTER TABLE on_call_shifts
        ADD CONSTRAINT {CONSTRAINT}
        EXCLUDE USING gist (
            schedule_id WITH =,
            tstzrange(starts_at, ends_at) WITH &&
        )
        """
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "on_call_shifts")
    # btree_gist is left installed: extensions are shared database state and
    # dropping one in a table-level downgrade could break unrelated objects.
