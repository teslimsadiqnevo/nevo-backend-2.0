"""Add admin-facing SSO connection health and roster sync management.

Revision ID: 20260812_0019
Revises: 20260812_0018
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260812_0019"
down_revision: str | Sequence[str] | None = "20260812_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

sso_connection_status_enum = postgresql.ENUM(
    "connected",
    "needs_attention",
    "disconnected",
    name="sso_connection_status",
    create_type=False,
)


def upgrade() -> None:
    sso_connection_status_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "school_sso_configurations",
        sa.Column(
            "connection_status",
            sso_connection_status_enum,
            nullable=False,
            server_default="connected",
        ),
    )
    op.add_column(
        "school_sso_configurations",
        sa.Column("last_connection_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "school_sso_configurations",
        sa.Column(
            "connection_checked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "school_sso_configurations",
        sa.Column("reauthorised_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "school_sso_configurations",
        sa.Column(
            "next_scheduled_sync_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "school_sso_configurations",
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "school_sso_configurations",
        sa.Column("disconnected_by_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_school_sso_configurations_disconnected_by_user_id_users",
        "school_sso_configurations",
        "users",
        ["disconnected_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # A configuration disabled before this migration was disconnected by
    # definition: that was the only way to turn one off.
    op.execute(
        """
        UPDATE school_sso_configurations
        SET connection_status = 'disconnected',
            disconnected_at = updated_at
        WHERE enabled IS false
        """
    )
    op.create_check_constraint(
        "disconnected_matches_timestamp",
        "school_sso_configurations",
        "(connection_status = 'disconnected') = (disconnected_at IS NOT NULL)",
    )

    op.add_column(
        "roster_sync_runs",
        sa.Column("failure_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "roster_sync_runs",
        sa.Column(
            "triggered_manually",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "roster_sync_runs",
        sa.Column("triggered_by_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_roster_sync_runs_triggered_by_user_id_users",
        "roster_sync_runs",
        "users",
        ["triggered_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "roster_sync_issues",
        sa.Column("resolution_hint", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("roster_sync_issues", "resolution_hint")
    op.drop_constraint(
        op.f("fk_roster_sync_runs_triggered_by_user_id_users"),
        "roster_sync_runs",
        type_="foreignkey",
    )
    op.drop_column("roster_sync_runs", "triggered_by_user_id")
    op.drop_column("roster_sync_runs", "triggered_manually")
    op.drop_column("roster_sync_runs", "failure_reason")

    op.drop_constraint(
        op.f("ck_school_sso_configurations_disconnected_matches_timestamp"),
        "school_sso_configurations",
        type_="check",
    )
    op.drop_constraint(
        op.f("fk_school_sso_configurations_disconnected_by_user_id_users"),
        "school_sso_configurations",
        type_="foreignkey",
    )
    op.drop_column("school_sso_configurations", "disconnected_by_user_id")
    op.drop_column("school_sso_configurations", "disconnected_at")
    op.drop_column("school_sso_configurations", "next_scheduled_sync_at")
    op.drop_column("school_sso_configurations", "reauthorised_at")
    op.drop_column("school_sso_configurations", "connection_checked_at")
    op.drop_column("school_sso_configurations", "last_connection_error")
    op.drop_column("school_sso_configurations", "connection_status")
    sso_connection_status_enum.drop(op.get_bind(), checkfirst=True)
