"""Add flexible staff permission scopes and invitation records.

Revision ID: 20260703_0004
Revises: 20260702_0003
Create Date: 2026-07-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260703_0004"
down_revision: str | Sequence[str] | None = "20260702_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

permission_scope_enum = postgresql.ENUM(
    "billing",
    "roster",
    "curriculum",
    "senco",
    "it_sso",
    "oversight",
    "teacher",
    name="permission_scope",
    create_type=False,
)
user_role_enum = postgresql.ENUM(
    "student",
    "teacher",
    "senco_admin",
    "other_admin",
    name="user_role",
    create_type=False,
)


def upgrade() -> None:
    permission_scope_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "admins",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", name="uq_admins_user_id"),
    )
    op.create_index("ix_admins_school_id", "admins", ["school_id"])

    op.create_table(
        "admin_scope_assignments",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "admin_id",
            sa.Uuid(),
            sa.ForeignKey("admins.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", permission_scope_enum, nullable=False),
        sa.Column(
            "granted_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at",
            name="revoked_after_grant",
        ),
    )
    op.create_index(
        "ix_admin_scope_assignments_admin_active",
        "admin_scope_assignments",
        ["admin_id", "revoked_at"],
    )
    op.create_index(
        "uq_admin_scope_assignments_active",
        "admin_scope_assignments",
        ["admin_id", "scope"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "admin_invitations",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "invited_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="expiry_after_creation",
        ),
        sa.CheckConstraint(
            "accepted_at IS NULL OR revoked_at IS NULL",
            name="not_accepted_and_revoked",
        ),
        sa.UniqueConstraint(
            "token_digest",
            name="uq_admin_invitations_token_digest",
        ),
    )
    op.create_index(
        "ix_admin_invitations_expires_at",
        "admin_invitations",
        ["expires_at"],
    )
    op.create_index(
        "uq_admin_invitations_active_user",
        "admin_invitations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(
            "accepted_at IS NULL AND revoked_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_admin_invitations_active_user",
        table_name="admin_invitations",
    )
    op.drop_index(
        "ix_admin_invitations_expires_at",
        table_name="admin_invitations",
    )
    op.drop_table("admin_invitations")

    op.drop_index(
        "uq_admin_scope_assignments_active",
        table_name="admin_scope_assignments",
    )
    op.drop_index(
        "ix_admin_scope_assignments_admin_active",
        table_name="admin_scope_assignments",
    )
    op.drop_table("admin_scope_assignments")

    op.drop_index("ix_admins_school_id", table_name="admins")
    op.drop_table("admins")
    permission_scope_enum.drop(op.get_bind(), checkfirst=True)
