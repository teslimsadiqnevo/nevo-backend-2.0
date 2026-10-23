"""Add withdrawal undo and optional audit details for lesson media."""

import sqlalchemy as sa

from alembic import op

revision = "20261023_0116"
down_revision = "20261023_0115"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "deferred_lesson_media",
        sa.Column("withdrawal_reason", sa.String(500), nullable=True),
    )
    op.add_column(
        "deferred_lesson_media",
        sa.Column(
            "withdrawal_reason_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "deferred_lesson_media",
        sa.Column("withdrawal_reason_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "deferred_lesson_media",
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "deferred_lesson_media",
        sa.Column(
            "restored_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "deferred_lesson_media",
        sa.Column("restored_by_name", sa.String(300), nullable=True),
    )


def downgrade():
    for name in (
        "restored_by_name",
        "restored_by",
        "restored_at",
        "withdrawal_reason_at",
        "withdrawal_reason_by",
        "withdrawal_reason",
    ):
        op.drop_column("deferred_lesson_media", name)
