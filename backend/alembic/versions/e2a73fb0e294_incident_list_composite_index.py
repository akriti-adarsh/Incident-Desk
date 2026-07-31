"""incident list composite index

Revision ID: e2a73fb0e294
Revises: 45ccd95d4da4
Create Date: 2026-07-30 20:19:12.460455

"""

from collections.abc import Sequence

from alembic import op

revision: str = "e2a73fb0e294"
down_revision: str | None = "45ccd95d4da4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_incidents_org_created_id", "incidents", ["org_id", "created_at", "id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_incidents_org_created_id", table_name="incidents")
