"""A teacher can correct a mark, and the correction is never silent.

An answer can be right in a way a comparison cannot see, so a teacher has to
be able to change how it was marked. But this is the one write where an adult
changes the record of what a child did, so it is append-only beside the
attempt rather than an in-place edit with nothing left behind: the attempt
carries the corrected mark so everything downstream reads the truth, and this
table says who decided, when, what the mark was before, and why.

T12 / SCRUM-350, 20 November.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261120_0146"
down_revision = "20261120_0145"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lesson_mark_overrides",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        # Null where the answer had never been marked at all, which is a
        # different situation from having been marked wrong.
        sa.Column("previous_correct", sa.Boolean(), nullable=True),
        sa.Column("corrected_to", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["lesson_question_attempts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        # RESTRICT: an override with no attributable teacher is not an audit
        # record. A departing teacher's account is deactivated, not deleted.
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="RESTRICT"),
        # A mark changed with no reason is indistinguishable from a mistake,
        # and the person who most needs the reason is whoever reads this row
        # months later - a parent asking, or the teacher themself.
        sa.CheckConstraint(
            "length(btrim(reason)) > 0", name="mark_has_a_reason"
        ),
        # Recording an override that changed nothing would put noise into the
        # one trail that has to stay readable.
        sa.CheckConstraint(
            "previous_correct IS DISTINCT FROM corrected_to",
            name="mark_changes_the_mark",
        ),
    )
    op.create_index(
        "ix_lesson_mark_overrides_attempt",
        "lesson_mark_overrides",
        ["attempt_id", "occurred_at"],
    )
    op.create_index(
        "ix_lesson_mark_overrides_student",
        "lesson_mark_overrides",
        ["student_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lesson_mark_overrides_student", table_name="lesson_mark_overrides"
    )
    op.drop_index(
        "ix_lesson_mark_overrides_attempt", table_name="lesson_mark_overrides"
    )
    op.drop_table("lesson_mark_overrides")
