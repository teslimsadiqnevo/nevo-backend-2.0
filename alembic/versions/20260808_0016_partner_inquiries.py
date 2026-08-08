"""Add landing page partner inquiries.

Revision ID: 20260808_0016
Revises: 20260711_0015
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260808_0016"
down_revision: str | Sequence[str] | None = "20260711_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

partner_inquiry_role_enum = postgresql.ENUM(
    "school_owner",
    "proprietor",
    "senco",
    "head_of_learning",
    "head_teacher",
    "other",
    name="partner_inquiry_role",
    create_type=False,
)
partner_inquiry_contact_method_enum = postgresql.ENUM(
    "email",
    "phone",
    name="partner_inquiry_contact_method",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    partner_inquiry_role_enum.create(bind, checkfirst=True)
    partner_inquiry_contact_method_enum.create(bind, checkfirst=True)

    op.create_table(
        "partner_inquiries",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("school_name", sa.String(length=255), nullable=False),
        sa.Column("role", partner_inquiry_role_enum, nullable=False),
        sa.Column("contact", sa.String(length=255), nullable=False),
        sa.Column(
            "contact_method",
            partner_inquiry_contact_method_enum,
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_partner_inquiries_created_at",
        "partner_inquiries",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_partner_inquiries_created_at",
        table_name="partner_inquiries",
    )
    op.drop_table("partner_inquiries")
    partner_inquiry_contact_method_enum.drop(op.get_bind(), checkfirst=True)
    partner_inquiry_role_enum.drop(op.get_bind(), checkfirst=True)
