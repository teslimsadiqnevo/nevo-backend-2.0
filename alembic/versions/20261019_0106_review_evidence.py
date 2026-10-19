"""One server-marked review update per concept and learning session."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261019_0106"
down_revision = "20261018_0105"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "concept_review_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "student_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "concept_id",
            sa.Uuid(),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("lesson_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("schedule_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "student_id", "concept_id", "session_id", name="uq_review_evidence_sitting"
        ),
    )


def downgrade():
    op.drop_table("concept_review_evidence")
