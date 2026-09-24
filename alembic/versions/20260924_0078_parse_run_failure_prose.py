"""A failed parse run says something a teacher can read, and can be quoted.

content_parse_runs carried only error_message, and the API served it under
the name failureReason - a field whose name promises prose and which was
delivering the first line of a stack trace. A console rendered it to teachers
verbatim, which is how a school owner came to read a Postgres error.

error_message stays exactly as it is, for reporting. These are the two fields
that should have been beside it, matching upload_jobs so the two doors into
the same pipeline report a failure the same way.

Revision ID: 20260924_0078
Revises: 20260924_0077
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260924_0078"
down_revision: str | Sequence[str] | None = "20260924_0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("content_parse_runs", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column(
        "content_parse_runs", sa.Column("incident_id", sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("content_parse_runs", "incident_id")
    op.drop_column("content_parse_runs", "failure_reason")
