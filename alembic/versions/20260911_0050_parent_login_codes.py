"""Sign a parent in with a code sent to the contact their school holds.

Revision ID: 20260911_0050
Revises: 20260909_0049
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260911_0050"
down_revision: str | Sequence[str] | None = "20260909_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "parent_login_codes",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Normalised, and the only handle we have before a parent is known.
        sa.Column("contact", sa.String(255), nullable=False),
        # Digest, never the code. A readable column here would be a list of
        # live credentials for every parent in the country.
        sa.Column("code_digest", sa.String(64), nullable=False),
        sa.Column(
            "parent_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("attempt_count >= 0", name="parent_login_code_attempts_valid"),
    )
    # The live-code lookup: one contact, newest first.
    op.create_index(
        "ix_parent_login_codes_contact_created",
        "parent_login_codes",
        ["contact", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_parent_login_codes_contact_created", table_name="parent_login_codes")
    op.drop_table("parent_login_codes")
