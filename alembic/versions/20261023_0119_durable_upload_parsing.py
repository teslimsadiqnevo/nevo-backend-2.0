"""Persist upload parse leases and recoverable parse metadata.

Revision ID: 20261023_0119
Revises: 20261023_0118
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "20261023_0119"
down_revision: str | Sequence[str] | None = "20261023_0118"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("upload_jobs", sa.Column("parse_lease_token", sa.Uuid(), nullable=True))
    op.add_column(
        "upload_jobs", sa.Column("parse_lease_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "upload_jobs",
        sa.Column("parse_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index(
        "ix_upload_jobs_parse_claim",
        "upload_jobs",
        ["status", "parse_lease_until", "created_at"],
    )
    op.add_column(
        "upload_source_blobs",
        sa.Column(
            "parse_metadata",
            JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("upload_source_blobs", "parse_metadata")
    op.drop_index("ix_upload_jobs_parse_claim", table_name="upload_jobs")
    op.drop_column("upload_jobs", "parse_attempts")
    op.drop_column("upload_jobs", "parse_lease_until")
    op.drop_column("upload_jobs", "parse_lease_token")
