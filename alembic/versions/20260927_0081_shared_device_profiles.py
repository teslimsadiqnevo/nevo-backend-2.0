"""Distinct profile avatars on each shared classroom device.

Revision ID: 20260927_0081
Revises: 20260927_0080
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260927_0081"
down_revision: str | Sequence[str] | None = "20260927_0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shared_device_profiles",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("avatar_shape", sa.String(length=24), nullable=False),
        sa.Column("avatar_colourway", sa.String(length=24), nullable=False),
        sa.Column("provisioned_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["provisioned_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "device_id", "student_id", name="uq_shared_device_profiles_device_student"
        ),
        sa.UniqueConstraint(
            "device_id",
            "avatar_shape",
            "avatar_colourway",
            name="uq_shared_device_profiles_device_avatar",
        ),
    )
    op.create_index(
        "ix_shared_device_profiles_school_device",
        "shared_device_profiles",
        ["school_id", "device_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shared_device_profiles_school_device", table_name="shared_device_profiles"
    )
    op.drop_table("shared_device_profiles")
