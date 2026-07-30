"""comment ordering

Revision ID: 3f51b8692cd0
Revises: 4e9c2d2a6a47
Create Date: 2026-07-30 16:45:14.005516

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f51b8692cd0"
down_revision: str | None = "4e9c2d2a6a47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "comments", sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False)
    )
    op.create_index("ix_comments_incident_id_seq", "comments", ["incident_id", "seq"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_comments_incident_id_seq", table_name="comments")
    op.drop_column("comments", "seq")
