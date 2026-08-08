"""Add system heartbeat table.

Revision ID: 20260808_0017
Revises: 20260808_0016
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260808_0017"
down_revision: str | Sequence[str] | None = "20260808_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_heartbeats",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("beat_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "beat_date",
            name="uq_system_heartbeats_beat_date",
        ),
    )


def downgrade() -> None:
    op.drop_table("system_heartbeats")
