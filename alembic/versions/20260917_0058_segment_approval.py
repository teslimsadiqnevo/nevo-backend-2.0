"""Let a teacher approve a segment's variants before children see them.

SCRUM-37 is explicit that approval is manual and deliberate and that the
teacher stays in control of what reaches students, and the screen has said so
since it was designed. The backend had no write for it, so every lesson was in
effect approved the moment it finished parsing.

Existing segments are backfilled as approved. The alternative - treating the
whole library as unapproved - would take every lesson already assigned to a
class dark until somebody walked it segment by segment, which punishes schools
for the feature arriving late.

Revision ID: 20260917_0058
Revises: 20260915_0057
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260917_0058"
down_revision: str | Sequence[str] | None = "20260915_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lesson_segments",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "lesson_segments",
        sa.Column(
            "approved_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Everything that already exists predates the gate. approved_by stays null
    # because nobody did approve these, and claiming a teacher had would be a
    # false record on a screen that shows who.
    op.execute("UPDATE lesson_segments SET approved_at = now()")
    op.create_index(
        "ix_lesson_segments_lesson_approved",
        "lesson_segments",
        ["lesson_id", "approved_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_lesson_segments_lesson_approved", table_name="lesson_segments")
    op.drop_column("lesson_segments", "approved_by")
    op.drop_column("lesson_segments", "approved_at")
