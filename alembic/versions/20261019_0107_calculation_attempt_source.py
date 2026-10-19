"""Allow the calculation source already supported by the answer API."""

import sqlalchemy as sa

from alembic import op

revision = "20261019_0107"
down_revision = "20261019_0106"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        op.f("ck_lesson_question_attempts_lesson_question_attempt_source_valid"),
        "lesson_question_attempts",
        type_="check",
    )
    op.create_check_constraint(
        "lesson_question_attempt_source_valid",
        "lesson_question_attempts",
        "source IN ('checkpoint', 'assessment', 'calculation')",
    )


def downgrade():
    # Do not delete legitimate calculation attempts to make an old constraint fit.
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM lesson_question_attempts WHERE source='calculation')")
    ):
        raise RuntimeError(
            "Calculation attempts exist; downgrade would invalidate learning records"
        )
    op.drop_constraint(
        op.f("ck_lesson_question_attempts_lesson_question_attempt_source_valid"),
        "lesson_question_attempts",
        type_="check",
    )
    op.create_check_constraint(
        "lesson_question_attempt_source_valid",
        "lesson_question_attempts",
        "source IN ('checkpoint', 'assessment')",
    )
