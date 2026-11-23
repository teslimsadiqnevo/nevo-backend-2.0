"""A refusal says why, in words a person can read.

Lydia, 23 November: the weekly adjudication of shadow-mode disagreements has
to read reasons, not category labels. Today v1 stores a category like
"privacy_abuse" and v2 stores a typed finding; both are our own vocabulary and
neither says what the checker actually objected to. Without a sentence, the
person reading the week's disagreements is guessing at two verdicts rather
than judging between them.

Nullable on purpose, and not backfilled. It is a sentence we ask the model
for and may not get, and a missing one must never fail the check that
produced it - a required field the model omits becomes a validation error,
then SafetyUnavailable, then a teacher's upload failing for no reason she
did anything about. The 71 historical refusals keep no reason because none
was ever asked for, and their material has expired anyway.

0149, 23 November 2026.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261123_0149"
down_revision = "20261122_0148"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_safety_events", sa.Column("reason", sa.Text(), nullable=True)
    )
    op.execute(
        """
        COMMENT ON COLUMN content_safety_events.reason IS
        'One sentence from the checker that made this decision, for a person '
        'adjudicating it later. Null means none was given, which is not the '
        'same as there being no reason.'
        """
    )


def downgrade() -> None:
    op.drop_column("content_safety_events", "reason")
