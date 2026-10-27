"""Track parent DOB recheck notices.

Revision ID: 20261027_0126
Revises: 20261027_0125
"""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0126"
down_revision = "20261027_0125"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("age_checks", sa.Column("parent_notified_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("age_checks", "parent_notified_at")
