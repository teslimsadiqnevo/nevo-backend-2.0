"""Capture TOSSE founding-partner leads.

Revision ID: 20260902_0038
Revises: 20260901_0037
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260902_0038"
down_revision: str | Sequence[str] | None = "20260901_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

intent_enum = postgresql.ENUM(
    "founding_partner",
    "pilot",
    "learn_more",
    name="partner_inquiry_intent",
    create_type=False,
)
source_enum = postgresql.ENUM(
    "website",
    "tosse_2026",
    name="partner_inquiry_source",
    create_type=False,
)


def upgrade() -> None:
    intent_enum.create(op.get_bind(), checkfirst=True)
    source_enum.create(op.get_bind(), checkfirst=True)

    # All nullable except source, which defaults: the existing website form
    # posts none of these and must keep working untouched.
    op.add_column("partner_inquiries", sa.Column("email", sa.String(255)))
    op.add_column("partner_inquiries", sa.Column("phone", sa.String(50)))
    op.add_column("partner_inquiries", sa.Column("student_count", sa.Integer()))
    op.add_column("partner_inquiries", sa.Column("intent", intent_enum))
    op.add_column(
        "partner_inquiries",
        sa.Column("source", source_enum, server_default="website", nullable=False),
    )
    op.create_check_constraint(
        "partner_inquiry_student_count_positive",
        "partner_inquiries",
        "student_count IS NULL OR student_count > 0",
    )
    # The booth view reads the newest leads for one source, repeatedly, on a
    # phone over event wifi.
    op.create_index(
        "ix_partner_inquiries_source_created",
        "partner_inquiries",
        ["source", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_partner_inquiries_source_created", table_name="partner_inquiries")
    op.drop_constraint(
        "ck_partner_inquiries_partner_inquiry_student_count_positive",
        "partner_inquiries",
    )
    for column in ("source", "intent", "student_count", "phone", "email"):
        op.drop_column("partner_inquiries", column)
    source_enum.drop(op.get_bind(), checkfirst=True)
    intent_enum.drop(op.get_bind(), checkfirst=True)
