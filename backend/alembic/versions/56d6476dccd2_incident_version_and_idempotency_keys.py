"""incident version and idempotency keys

Revision ID: 56d6476dccd2
Revises: fa12bdbddda4
Create Date: 2026-07-30 16:56:09.274994

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "56d6476dccd2"
down_revision: str | None = "fa12bdbddda4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=False),
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
            name=op.f("fk_idempotency_keys_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("org_id", "key", name=op.f("pk_idempotency_keys")),
    )
    op.add_column(
        "incidents", sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False)
    )


def downgrade() -> None:
    op.drop_column("incidents", "version")
    op.drop_table("idempotency_keys")
