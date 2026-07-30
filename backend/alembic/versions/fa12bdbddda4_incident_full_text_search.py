"""incident full text search

Revision ID: fa12bdbddda4
Revises: 3f51b8692cd0
Create Date: 2026-07-30 16:48:21.662497

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fa12bdbddda4"
down_revision: str | None = "3f51b8692cd0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', title || ' ' || description)", persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_incidents_search_vector",
        "incidents",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_incidents_search_vector", table_name="incidents", postgresql_using="gin")
    op.drop_column("incidents", "search_vector")
