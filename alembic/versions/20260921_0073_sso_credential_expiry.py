"""A school is warned before its SSO credential stops working.

Microsoft expires OAuth client secrets - two years by default - and the first
anyone knew was every teacher in a school failing to sign in on a Monday.
Nevo cannot read the expiry from the provider, so it is recorded when the
connection is set up and the health screen counts down to it.

Revision ID: 20260921_0073
Revises: 20260921_0072
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260921_0073"
down_revision: str | Sequence[str] | None = "20260921_0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "school_sso_configurations",
        sa.Column("credential_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("school_sso_configurations", "credential_expires_at")
