"""A failed parse can say something a teacher can act on, and be quoted.

Two things were missing on a job that ends failed. It carried only
``error_message``, which is whatever the driver said - the console rendered
it as teacher-facing copy once, and a raw exception is a bad thing to show a
person. And it carried no reference, so a teacher looking at a failed parse
had nothing to quote and we had nothing to match it to in the log.

``error_message`` stays exactly as it is, for reporting. These are the two
fields that should have existed beside it.

Revision ID: 20260924_0076
Revises: 20260922_0075
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260924_0076"
down_revision: str | Sequence[str] | None = "20260922_0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("upload_jobs", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column("upload_jobs", sa.Column("incident_id", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("upload_jobs", "incident_id")
    op.drop_column("upload_jobs", "failure_reason")
