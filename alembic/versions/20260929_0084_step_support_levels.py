"""Record how much help each segment's working needs. SCRUM-185.

The support ladder is what the pipeline drops down when it cannot do the thing
above: the child builds each step, or picks the next move from generated
candidates, or the steps are revealed with nothing judged, or it is an ordinary
segment with Simplify, Expand and Slower.

Stored per segment rather than inferred, because the point of the ladder is to
be measured. Of 344 topics mapped across the NERDC curricula and the WAEC
syllabuses, 278 should reach the top rung and 22 should fall to the bottom -
and the only way to know whether that holds for real lessons is to record what
each one actually got.

Revision ID: 20260929_0084
Revises: 20260929_0083
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260929_0084"
down_revision: str | Sequence[str] | None = "20260929_0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain strings rather than an enum: the ladder is expected to gain rungs
    # once coverage is measured, and an enum makes that a migration on a table
    # with a row per segment of every lesson.
    op.add_column(
        "lesson_segments", sa.Column("support_level", sa.String(length=16), nullable=True)
    )
    op.add_column(
        "lesson_segments", sa.Column("working_layout", sa.String(length=16), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("lesson_segments", "working_layout")
    op.drop_column("lesson_segments", "support_level")
