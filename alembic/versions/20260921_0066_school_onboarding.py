"""Upload, derive, confirm, pay, activate.

A school could create classes, add teachers and add students without paying
anything, so an upload has to be able to propose people without them existing.
Uploaded rows live here, uncommitted and editable, until the school confirms
the derived list and settles the invoice.

Schools already in the product are marked activated: they were onboarded
before this order existed, and putting a live school back behind a payment
gate it never met would take its console away.

Revision ID: 20260921_0066
Revises: 20260921_0065
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260921_0066"
down_revision: str | Sequence[str] | None = "20260921_0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAGE = postgresql.ENUM(
    "uploading",
    "confirmed",
    "awaiting_payment",
    "activated",
    name="onboarding_stage",
    create_type=False,
)
ROW_KIND = postgresql.ENUM(
    "teacher",
    "student",
    name="onboarding_row_kind",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    STAGE.create(bind, checkfirst=True)
    ROW_KIND.create(bind, checkfirst=True)

    op.create_table(
        "school_onboardings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("stage", STAGE, server_default="uploading", nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(stage = 'activated') = (activated_at IS NOT NULL)",
            name="onboarding_activation_matches_stage",
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_school_onboardings_school",
        "school_onboardings",
        ["school_id"],
        unique=True,
    )

    op.create_table(
        "onboarding_rows",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("onboarding_id", sa.Uuid(), nullable=False),
        sa.Column("kind", ROW_KIND, nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column(
            "values",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("class_name", sa.String(length=255), nullable=True),
        sa.Column("normalised_class_name", sa.String(length=255), nullable=True),
        sa.Column("rejected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("rejection_field", sa.String(length=80), nullable=True),
        sa.Column("rejection_value", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("excluded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("row_number >= 1", name="onboarding_row_number_positive"),
        sa.CheckConstraint(
            "(rejected = false) OR (rejection_reason IS NOT NULL)",
            name="onboarding_rejection_has_a_reason",
        ),
        sa.ForeignKeyConstraint(
            ["onboarding_id"],
            ["school_onboardings.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_onboarding_rows_onboarding_kind",
        "onboarding_rows",
        ["onboarding_id", "kind", "row_number"],
    )
    op.create_index(
        "ix_onboarding_rows_class",
        "onboarding_rows",
        ["onboarding_id", "normalised_class_name"],
    )

    # Schools onboarded before this order existed keep their console.
    op.execute(
        """
        INSERT INTO school_onboardings (school_id, stage, activated_at, confirmed_at)
        SELECT id, 'activated', created_at, created_at FROM schools
        """
    )


def downgrade() -> None:
    op.drop_index("ix_onboarding_rows_class", table_name="onboarding_rows")
    op.drop_index("ix_onboarding_rows_onboarding_kind", table_name="onboarding_rows")
    op.drop_table("onboarding_rows")
    op.drop_index("ix_school_onboardings_school", table_name="school_onboardings")
    op.drop_table("school_onboardings")
    bind = op.get_bind()
    ROW_KIND.drop(bind, checkfirst=True)
    STAGE.drop(bind, checkfirst=True)
