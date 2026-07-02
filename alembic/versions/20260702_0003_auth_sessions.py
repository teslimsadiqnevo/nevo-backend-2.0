"""Add manual login identifier, revocable sessions, and auth audit tables.

Revision ID: 20260702_0003
Revises: 20260702_0002
Create Date: 2026-07-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260702_0003"
down_revision: str | Sequence[str] | None = "20260702_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role_enum = postgresql.ENUM(
    "student",
    "teacher",
    "senco_admin",
    "other_admin",
    name="user_role",
    create_type=False,
)


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("login_identifier", sa.String(length=50), nullable=True),
    )
    op.create_unique_constraint(
        "uq_users_school_id_login_identifier",
        "users",
        ["school_id", "login_identifier"],
    )
    op.create_index(
        "uq_schools_school_code_ci",
        "schools",
        [sa.text("lower(school_code)")],
        unique=True,
    )
    op.create_index(
        "uq_users_email_ci",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "uq_users_school_login_identifier_ci",
        "users",
        ["school_id", sa.text("lower(login_identifier)")],
        unique=True,
        postgresql_where=sa.text("login_identifier IS NOT NULL"),
    )

    op.create_table(
        "auth_sessions",
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
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=32), nullable=True),
        sa.Column(
            "replaced_by_session_id",
            sa.Uuid(),
            sa.ForeignKey("auth_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="expiry_after_creation",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name="revocation_fields_consistent",
        ),
        sa.UniqueConstraint(
            "token_digest",
            name="uq_auth_sessions_token_digest",
        ),
    )
    op.create_index(
        "ix_auth_sessions_user_id",
        "auth_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_auth_sessions_expires_at",
        "auth_sessions",
        ["expires_at"],
    )
    op.create_index(
        "ix_auth_sessions_user_active",
        "auth_sessions",
        ["user_id", "revoked_at"],
    )
    op.create_index(
        "uq_auth_sessions_one_active_student",
        "auth_sessions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("role = 'student' AND revoked_at IS NULL"),
    )

    op.create_table(
        "auth_login_attempts",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("identity_digest", sa.String(length=64), nullable=False),
        sa.Column("ip_digest", sa.String(length=64), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_auth_login_attempts_identity_occurred",
        "auth_login_attempts",
        ["identity_digest", "occurred_at"],
    )
    op.create_index(
        "ix_auth_login_attempts_ip_occurred",
        "auth_login_attempts",
        ["ip_digest", "occurred_at"],
    )

    op.create_table(
        "auth_audit_events",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("auth_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("identity_digest", sa.String(length=64), nullable=True),
        sa.Column("ip_digest", sa.String(length=64), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_auth_audit_events_user_occurred",
        "auth_audit_events",
        ["user_id", "occurred_at"],
    )
    op.create_index(
        "ix_auth_audit_events_type_occurred",
        "auth_audit_events",
        ["event_type", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_audit_events_type_occurred",
        table_name="auth_audit_events",
    )
    op.drop_index(
        "ix_auth_audit_events_user_occurred",
        table_name="auth_audit_events",
    )
    op.drop_table("auth_audit_events")

    op.drop_index(
        "ix_auth_login_attempts_ip_occurred",
        table_name="auth_login_attempts",
    )
    op.drop_index(
        "ix_auth_login_attempts_identity_occurred",
        table_name="auth_login_attempts",
    )
    op.drop_table("auth_login_attempts")

    op.drop_index(
        "uq_auth_sessions_one_active_student",
        table_name="auth_sessions",
    )
    op.drop_index("ix_auth_sessions_user_active", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_index(
        "uq_users_school_login_identifier_ci",
        table_name="users",
    )
    op.drop_index("uq_users_email_ci", table_name="users")
    op.drop_index("uq_schools_school_code_ci", table_name="schools")
    op.drop_constraint(
        "uq_users_school_id_login_identifier",
        "users",
        type_="unique",
    )
    op.drop_column("users", "login_identifier")
