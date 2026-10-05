"""An administrator proves they own the address they registered with.

The first account in a school holds the highest permissions in it and was the
only account that never confirmed its address. Rows are kept once used or
replaced, because a person following a link from an older email has to be told
which of the three things happened.

Every account that exists today is treated as confirmed. They were created
before the rule, they are in daily use, and locking a live school out of its
own console to enforce a rule retroactively would be the wrong way round.

Revision ID: 20260921_0065
Revises: 20260921_0064
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260921_0065"
down_revision: str | Sequence[str] | None = "20260921_0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE users SET email_confirmed_at = created_at WHERE email IS NOT NULL")

    op.create_table(
        "email_confirmations",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("token_digest", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest", name="uq_email_confirmations_token_digest"),
    )
    op.create_index(
        "ix_email_confirmations_user_created",
        "email_confirmations",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_confirmations_user_created", table_name="email_confirmations")
    op.drop_table("email_confirmations")
    op.drop_column("users", "email_confirmed_at")
