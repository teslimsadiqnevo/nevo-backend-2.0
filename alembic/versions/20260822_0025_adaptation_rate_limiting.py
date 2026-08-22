"""Add adaptation suppressed signal event type.

Revision ID: 20260822_0025
Revises: 20260822_0024
Create Date: 2026-08-22 00:25:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260822_0025"
down_revision: str | None = "20260822_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE signal_event_type ADD VALUE IF NOT EXISTS 'adaptation_suppressed'")


def downgrade() -> None:
    # PostgreSQL enum values are intentionally not removed on downgrade.
    pass
