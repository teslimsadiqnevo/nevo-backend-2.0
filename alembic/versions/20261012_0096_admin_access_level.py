"""Distinguish senior and standard school administrators.

Revision ID: 20261012_0096
Revises: 20261013_0098
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261012_0096"
down_revision = "20261013_0098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    level = sa.Enum("senior", "standard", name="admin_access_level")
    level.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "admins",
        sa.Column(
            "access_level",
            level,
            nullable=False,
            server_default="standard",
        ),
    )
    # Existing founding admins are the accounts created with their schools.
    op.execute(
        "UPDATE admins SET access_level = 'senior' WHERE created_by_user_id IS NULL"
    )


def downgrade() -> None:
    op.drop_column("admins", "access_level")
    sa.Enum(name="admin_access_level").drop(op.get_bind(), checkfirst=True)
