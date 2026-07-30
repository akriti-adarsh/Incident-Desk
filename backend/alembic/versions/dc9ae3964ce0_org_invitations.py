"""org invitations

Revision ID: dc9ae3964ce0
Revises: 0afa51c2595b
Create Date: 2026-07-30 16:21:19.740823

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "dc9ae3964ce0"
down_revision: str | None = "0afa51c2595b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "owner",
                "admin",
                "responder",
                "viewer",
                name="membership_role",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
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
            ["invited_by"],
            ["users.id"],
            name=op.f("fk_org_invitations_invited_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_org_invitations_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_org_invitations_token_hash")),
    )
    op.create_index(op.f("ix_org_invitations_email"), "org_invitations", ["email"], unique=False)
    op.create_index(
        op.f("ix_org_invitations_invited_by"), "org_invitations", ["invited_by"], unique=False
    )
    op.create_index(op.f("ix_org_invitations_org_id"), "org_invitations", ["org_id"], unique=False)
    op.create_index(
        "uq_org_invitations_pending",
        "org_invitations",
        ["org_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_org_invitations_pending",
        table_name="org_invitations",
        postgresql_where=sa.text("accepted_at IS NULL"),
    )
    op.drop_index(op.f("ix_org_invitations_org_id"), table_name="org_invitations")
    op.drop_index(op.f("ix_org_invitations_invited_by"), table_name="org_invitations")
    op.drop_index(op.f("ix_org_invitations_email"), table_name="org_invitations")
    op.drop_table("org_invitations")
