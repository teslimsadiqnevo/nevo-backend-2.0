"""A lesson is finished when we say so, not when the app says so.

completion_status is the player's declaration: it sends "completed" and we
record it. Of 41 sittings marked completed, 22 have no recorded answer at
all, so the number a learner profile is built from is half noise. Lydia,
22 November: the number is the lessons where the check was taken and marked,
stored as our decision, and re-judge the existing ones.

This adds the column. It does not backfill, because which rule to store is
not settled - and the measured counts are why:

    18  the app says completed AND a check was marked
    27  a check was marked AND the sitting has ended
    31  a check was marked, full stop

18 is the number Lydia reasoned from, and it is the one rule of the three
that still requires the app's claim. So "our decision rather than the app's
claim" and "18" cannot both hold: dropping the claim gives 27. That is a
question for her rather than a thing to pick here, so the backfill is a
separate script with the rule as an argument and a dry run that prints all
three.

T19-adjacent, 22 November.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261122_0148"
down_revision = "20261120_0147"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lesson_sessions",
        sa.Column("verified_complete_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The profile counts finished lessons per learner, newest first, so the
    # index carries the learner and the judgement together.
    op.create_index(
        "ix_lesson_sessions_verified_complete",
        "lesson_sessions",
        ["student_id", "verified_complete_at"],
    )
    op.execute(
        """
        COMMENT ON COLUMN lesson_sessions.verified_complete_at IS
        'When Nevo judged the lesson finished, on its own evidence. Null means '
        'not judged finished, which is not the same as the child not having '
        'finished. completion_status remains the player''s own declaration.'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lesson_sessions_verified_complete", table_name="lesson_sessions"
    )
    op.drop_column("lesson_sessions", "verified_complete_at")
