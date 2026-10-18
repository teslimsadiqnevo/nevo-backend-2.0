"""Connect session delivery, marked evidence and curriculum eligibility."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261018_0102"
down_revision = "20261014_0101"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "lesson_sessions",
        sa.Column(
            "delivery_state",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "lesson_question_attempts", sa.Column("response_time_ms", sa.Integer(), nullable=True)
    )
    op.add_column(
        "lesson_question_attempts",
        sa.Column("hint_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "concepts", sa.Column("curriculum_position", sa.Float(), nullable=False, server_default="0")
    )
    op.add_column(
        "concepts",
        sa.Column(
            "prerequisite_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_concept_curriculum_position", "concepts", "curriculum_position BETWEEN 0 AND 1"
    )
    op.create_check_constraint(
        "ck_attempt_response_time",
        "lesson_question_attempts",
        "response_time_ms IS NULL OR response_time_ms >= 0",
    )
    op.create_check_constraint(
        "ck_attempt_hint_count", "lesson_question_attempts", "hint_count >= 0"
    )
    op.execute("""WITH ranked AS (
        SELECT id, percent_rank() OVER (PARTITION BY school_id, subject ORDER BY created_at, id) AS position
        FROM concepts
    ) UPDATE concepts SET curriculum_position = ranked.position FROM ranked WHERE concepts.id = ranked.id""")


def downgrade():
    op.drop_constraint("ck_attempt_hint_count", "lesson_question_attempts")
    op.drop_constraint("ck_attempt_response_time", "lesson_question_attempts")
    op.drop_constraint("ck_concept_curriculum_position", "concepts")
    op.drop_column("concepts", "prerequisite_ids")
    op.drop_column("concepts", "curriculum_position")
    op.drop_column("lesson_question_attempts", "hint_count")
    op.drop_column("lesson_question_attempts", "response_time_ms")
    op.drop_column("lesson_sessions", "delivery_state")
