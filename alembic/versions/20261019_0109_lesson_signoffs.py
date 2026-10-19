"""Lesson-wide professional sign-offs; stage until after the demo."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261019_0109"
down_revision = "20261019_0108"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lesson_review_signoffs",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "lesson_id", sa.Uuid(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column(
            "approved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("approved_by_name", sa.String(250), nullable=False),
        sa.Column(
            "approved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('key_points', 'rewrites')", name="kind_valid"),
    )
    op.create_index(
        "ix_lesson_review_signoffs_lesson_kind",
        "lesson_review_signoffs",
        ["lesson_id", "kind", "approved_at"],
    )


def downgrade():
    op.drop_table("lesson_review_signoffs")
