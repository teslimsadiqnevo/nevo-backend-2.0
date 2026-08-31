"""Track recurring background job runs and retention anonymisation.

Revision ID: 20260831_0033
Revises: 20260831_0032
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260831_0033"
down_revision: str | Sequence[str] | None = "20260831_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_job_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("job_name", sa.String(80), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True)),
        sa.Column("last_finished_at", sa.DateTime(timezone=True)),
        sa.Column("last_status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("last_summary", sa.Text()),
        sa.Column("last_error", sa.Text()),
        sa.Column("run_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("job_name", name="uq_scheduled_job_runs_job_name"),
    )
    op.add_column("users", sa.Column("anonymised_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_users_retention_sweep",
        "users",
        ["status", "deactivated_at"],
        postgresql_where=sa.text("anonymised_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_retention_sweep", table_name="users")
    op.drop_column("users", "anonymised_at")
    op.drop_table("scheduled_job_runs")
