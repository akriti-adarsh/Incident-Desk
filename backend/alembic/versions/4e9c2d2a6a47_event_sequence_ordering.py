"""event sequence ordering

Revision ID: 4e9c2d2a6a47
Revises: dc9ae3964ce0
Create Date: 2026-07-30 16:41:40.102757

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4e9c2d2a6a47"
down_revision: str | None = "dc9ae3964ce0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "incident_events",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
    )
    op.create_index(
        "ix_incident_events_incident_id_seq",
        "incident_events",
        ["incident_id", "seq"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_incident_events_incident_id_seq", table_name="incident_events")
    op.drop_column("incident_events", "seq")
