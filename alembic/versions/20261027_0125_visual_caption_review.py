"""Hold descriptions of stored pictures for teacher approval.

Revision ID: 20261027_0125
Revises: 20261027_0124
"""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0125"
down_revision = "20261027_0124"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("visual_safety_restamps", sa.Column("caption_candidate", sa.String(300)))
    op.add_column("visual_safety_restamps", sa.Column("caption_approved_at", sa.DateTime(timezone=True)))
    op.add_column("visual_safety_restamps", sa.Column("caption_approved_by", sa.Uuid()))
    op.create_foreign_key(
        "fk_visual_restamp_caption_approver", "visual_safety_restamps", "users",
        ["caption_approved_by"], ["id"], ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_visual_restamp_caption_approver", "visual_safety_restamps", type_="foreignkey")
    op.drop_column("visual_safety_restamps", "caption_approved_by")
    op.drop_column("visual_safety_restamps", "caption_approved_at")
    op.drop_column("visual_safety_restamps", "caption_candidate")
