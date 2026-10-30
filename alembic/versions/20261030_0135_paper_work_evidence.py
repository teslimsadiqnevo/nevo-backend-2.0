"""Store only step marks from the no-camera paper-work route."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261030_0135"
down_revision = "20261030_0134"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "paper_work_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("lesson_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", sa.Uuid(), sa.ForeignKey("lesson_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.String(160), nullable=False),
        sa.Column("client_submission_id", sa.Uuid()),
        sa.Column("marks", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("client_submission_id", name="uq_paper_work_client_submission"),
    )
    op.create_index("ix_paper_work_evidence_student_created", "paper_work_evidence", ["student_id", "created_at"])


def downgrade():
    op.drop_index("ix_paper_work_evidence_student_created", table_name="paper_work_evidence")
    op.drop_table("paper_work_evidence")
