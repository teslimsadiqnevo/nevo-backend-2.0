"""Keep the teacher's name on stored-image caption sign-off.

Revision ID: 20261027_0127
Revises: 20261027_0126
"""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0127"
down_revision = "20261027_0126"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("visual_safety_restamps", sa.Column("caption_approved_by_name", sa.String(300)))


def downgrade():
    op.drop_column("visual_safety_restamps", "caption_approved_by_name")
