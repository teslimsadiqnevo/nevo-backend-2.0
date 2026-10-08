"""Accept stable chunk visibility events for chunked reading.

Revision ID: 20261008_0092
Revises: 20261007_0091
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261008_0092"
down_revision = "20261007_0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lesson_assignments",
        sa.Column("cancellation_reason", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "lesson_assignments",
        sa.Column("recall_withdrawn", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    statement = (
        "ALTER TYPE signal_event_type ADD VALUE IF NOT EXISTS "
        "'reading_chunk_viewed'"
    )
    if op.get_context().as_sql:
        op.execute(statement)
        return
    connection = op.get_bind()
    connection.execute(sa.text("COMMIT"))
    connection.execute(sa.text(statement))


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed without rebuilding the type.
    op.drop_column("lesson_assignments", "recall_withdrawn")
    op.drop_column("lesson_assignments", "cancellation_reason")
