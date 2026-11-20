"""An AI call records its lesson, and what the cache did.

Lydia, 20 November: everything about pricing is blocked on the per-learner
runtime cost of one lesson. Every model call has been recorded for months
with its model, tokens and an estimated cost, and the row can already carry
the learner - but not the lesson, so "one learner across one lesson" could
only be approximated by a time window. The lesson id was already reaching
the gateway on the safety context and was simply never written down.

The cache counts go in for two reasons. The cost formula already used them -
a cache write is 1.25x a fresh input token and a read is a tenth of one - so
the figure depended on numbers nothing stored. And without them there is no
way to answer "is prompt caching working", which is the question L6's
caching change exists to settle.

Both additive and nullable or defaulted, so the running build is unaffected
until it is redeployed.

L2, 20 November.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261120_0145"
down_revision = "20261120_0144"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_gateway_calls", sa.Column("lesson_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_ai_gateway_calls_lesson_id",
        "ai_gateway_calls",
        "lessons",
        ["lesson_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_ai_gateway_calls_lesson",
        "ai_gateway_calls",
        ["lesson_id", "created_at"],
    )
    # The per-learner question is asked by learner and lesson together, which
    # is the whole point of the column.
    op.create_index(
        "ix_ai_gateway_calls_student_lesson",
        "ai_gateway_calls",
        ["student_id", "lesson_id"],
    )
    for column in ("cache_creation_input_tokens", "cache_read_input_tokens"):
        op.add_column(
            "ai_gateway_calls",
            sa.Column(
                column,
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    # Historic rows keep a null lesson. They are not backfilled, and that is
    # deliberate: the only way to guess one now would be to match a call's
    # timestamp against a lesson's, which would invent attribution for the
    # exact figure this column exists to make trustworthy. The 2,626 calls
    # recorded before today stay as a total without a per-lesson breakdown,
    # and the first real measured lesson run is what produces the number.
    op.execute(
        """
        COMMENT ON COLUMN ai_gateway_calls.lesson_id IS
        'Null on rows recorded before 20 Nov 2026; never backfilled, because '
        'guessing attribution from timestamps would corrupt the per-learner '
        'cost figure this column exists to produce.'
        """
    )


def downgrade() -> None:
    op.drop_column("ai_gateway_calls", "cache_read_input_tokens")
    op.drop_column("ai_gateway_calls", "cache_creation_input_tokens")
    op.drop_index("ix_ai_gateway_calls_student_lesson", table_name="ai_gateway_calls")
    op.drop_index("ix_ai_gateway_calls_lesson", table_name="ai_gateway_calls")
    op.drop_constraint(
        "fk_ai_gateway_calls_lesson_id", "ai_gateway_calls", type_="foreignkey"
    )
    op.drop_column("ai_gateway_calls", "lesson_id")
