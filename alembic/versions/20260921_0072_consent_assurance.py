"""The four things the school agreement asks for that the product never had.

A separate consent for the transfer outside Nigeria, a date of birth checked
against two sources rather than one, a record of a parent who was asked and
did not answer, and the fields a consent record is defined as carrying.

The learner-facing halves of these - a thirty-day window, deletion after it,
withdrawal from a parent's own account - are code rather than schema.

Revision ID: 20260921_0072
Revises: 20260921_0071
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260921_0072"
down_revision: str | Sequence[str] | None = "20260921_0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGE_CHECK_STATE = postgresql.ENUM(
    "matched",
    "mismatch",
    "resolved",
    "awaiting_parent",
    name="age_check_state",
    create_type=False,
)
REFUSAL_REASON = postgresql.ENUM(
    "no_response",
    "declined",
    "withdrawn",
    name="consent_refusal_reason",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    # A parent agreeing to their child using Nevo has not agreed to their
    # child's lesson text leaving the country. Postgres enums only grow, and
    # this one has to grow before anything can be written with it.
    op.execute("ALTER TYPE consent_type ADD VALUE IF NOT EXISTS 'cross_border_transfer'")
    op.execute("COMMIT")

    AGE_CHECK_STATE.create(bind, checkfirst=True)
    REFUSAL_REASON.create(bind, checkfirst=True)

    op.create_table(
        "age_checks",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("school_date_of_birth", sa.Date(), nullable=True),
        sa.Column("parent_date_of_birth", sa.Date(), nullable=True),
        sa.Column("state", AGE_CHECK_STATE, server_default="awaiting_parent", nullable=False),
        sa.Column("agreed_date_of_birth", sa.Date(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "(state = 'resolved')"
            " = (resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL)",
            name="age_check_resolution_matches_state",
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_age_checks_student", "age_checks", ["student_id"], unique=True)
    op.create_index(
        "ix_age_checks_school_state",
        "age_checks",
        ["school_id", "state"],
        postgresql_where=sa.text("state = 'mismatch'"),
    )

    op.create_table(
        "consent_refusals",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        # Deliberately not a foreign key: the learner row is removed thirty
        # days after this is written, and a refusal that vanishes with it
        # would let the school ask the same parent again the next morning.
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("contact_digest", sa.String(length=64), nullable=False),
        sa.Column("reason", REFUSAL_REASON, nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("roster_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_consent_refusals_student_contact",
        "consent_refusals",
        ["student_id", "contact_digest"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_consent_refusals_student_contact", table_name="consent_refusals")
    op.drop_table("consent_refusals")
    op.drop_index("ix_age_checks_school_state", table_name="age_checks")
    op.drop_index("ix_age_checks_student", table_name="age_checks")
    op.drop_table("age_checks")
    bind = op.get_bind()
    REFUSAL_REASON.drop(bind, checkfirst=True)
    AGE_CHECK_STATE.drop(bind, checkfirst=True)
    # cross_border_transfer stays on the consent_type enum: Postgres cannot
    # drop an enum value, and rows may already reference it.
