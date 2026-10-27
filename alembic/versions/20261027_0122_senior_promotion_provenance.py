"""Record who promoted each senior administrator and when.

Revision ID: 20261027_0122
Revises: 20261025_0121
"""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0122"
down_revision = "20261025_0121"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("admins", sa.Column("senior_promoted_by", sa.Uuid(), nullable=True))
    op.add_column("admins", sa.Column("senior_promoted_by_name", sa.String(length=250), nullable=True))
    op.add_column("admins", sa.Column("senior_promoted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_admins_senior_promoted_by_users", "admins", "users",
        ["senior_promoted_by"], ["id"], ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_admins_senior_promoted_by_users", "admins", type_="foreignkey")
    op.drop_column("admins", "senior_promoted_at")
    op.drop_column("admins", "senior_promoted_by_name")
    op.drop_column("admins", "senior_promoted_by")
