"""Nobody holds the deepest per-child view unless a school gave it to them.

The registering administrator was granted every scope, learning support
included, so every school began with its proprietor holding the deepest view
of every child in it. That grant is now a decision with a record behind it.

Existing schools keep whoever holds the scope today, recorded as granted at
the school's creation by the administrator who registered it. That is what
happened, and rewriting it as nobody would take a working console away from
a school mid-term.

Revision ID: 20260921_0069
Revises: 20260921_0068
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260921_0069"
down_revision: str | Sequence[str] | None = "20260921_0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_support_grants",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("holder_user_id", sa.Uuid(), nullable=False),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("handed_over", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["holder_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learning_support_grants_school_holder",
        "learning_support_grants",
        ["school_id", "holder_user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.execute(
        """
        INSERT INTO learning_support_grants
            (school_id, holder_user_id, granted_by_user_id, granted_at)
        SELECT DISTINCT ON (a.school_id, a.user_id)
               a.school_id, a.user_id, a.user_id, u.created_at
        FROM admin_scope_assignments s
        JOIN admins a ON a.id = s.admin_id
        JOIN users u ON u.id = a.user_id
        WHERE s.scope = 'senco'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_learning_support_grants_school_holder",
        table_name="learning_support_grants",
    )
    op.drop_table("learning_support_grants")
