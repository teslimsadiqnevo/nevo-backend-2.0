"""A teacher can state a class's subjects, and the library can say why.

Subjects were derived only, from the subjects of lessons assigned to a class,
so a class with nothing assigned yet was blank and a teacher had no way to
say what it is taught. Stated subjects replace the derived list rather than
merging with it: a teacher who writes a list and still sees a subject they did
not write has no way to remove it, so a merging control would be lying.

And a lesson that failed to parse carried its reason only on the parse run.
The library list has the lesson and not the run, so a card saying "couldn't be
processed" would have been one read per row to render one sentence.

Revision ID: 20260924_0079
Revises: 20260924_0078
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260924_0079"
down_revision: str | Sequence[str] | None = "20260924_0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "classes",
        sa.Column(
            "stated_subjects",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("lessons", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column("lessons", sa.Column("incident_id", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("lessons", "incident_id")
    op.drop_column("lessons", "failure_reason")
    op.drop_column("classes", "stated_subjects")
