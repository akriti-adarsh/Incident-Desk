"""org metrics daily

Revision ID: 45ccd95d4da4
Revises: 56d6476dccd2
Create Date: 2026-07-30 18:08:46.503809

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "45ccd95d4da4"
down_revision: str | None = "56d6476dccd2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_metrics_daily",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("incidents_created", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("incidents_resolved", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("mtta_seconds", sa.Float(), nullable=True),
        sa.Column("mttr_seconds", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_org_metrics_daily_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("org_id", "day", name=op.f("pk_org_metrics_daily")),
    )


def downgrade() -> None:
    op.drop_table("org_metrics_daily")
