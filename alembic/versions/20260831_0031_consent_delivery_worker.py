"""Make parent consent delivery retryable by a worker.

Revision ID: 20260831_0031
Revises: 20260830_0030
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260831_0031"
down_revision: str | Sequence[str] | None = "20260830_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE consent_delivery_status ADD VALUE IF NOT EXISTS 'processing'")
    op.add_column(
        "consent_notification_outbox",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "consent_notification_outbox",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_consent_notification_outbox_due",
        "consent_notification_outbox",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_consent_notification_outbox_due",
        table_name="consent_notification_outbox",
    )
    op.drop_column("consent_notification_outbox", "next_attempt_at")
    op.drop_column("consent_notification_outbox", "attempt_count")
