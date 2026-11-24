"""A guardian consents for a /me learner without creating an account.

/me, Phase 1b. In the school product a parent consents through a school's
link and is given a parent account, and the consent record names that
account (confirmation_source 'parent', confirmed_by_parent_id). A /me learner
under eighteen nominates their own guardian; the guardian consents from a
link and no account is made for them. Ruling A, 24 November 2026.

So the record gains a third source, 'guardian', which names no admin and no
parent account, and must name the person who consented
(parent_name_on_form) - a confirmation that identifies nobody is not one.

guardian_invitations holds the nomination: who the learner named, the link
sent to them, how often it was sent, and when (if) they answered. Its first
row's created_at starts the fourteen-day dormancy clock.

0151, 24 November 2026.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261124_0151"
down_revision = "20261124_0150"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_consent_records_confirmation_fields_match_status"

WITH_GUARDIAN = """
(status IN ('pending', 'not_sent') AND confirmation_source IS NULL
 AND confirmed_by_admin_id IS NULL AND confirmed_by_parent_id IS NULL
 AND confirmed_via IS NULL AND confirmed_at IS NULL)
OR
(status IN ('confirmed', 'withdrawn') AND confirmed_via IS NOT NULL AND confirmed_at IS NOT NULL
 AND ((confirmation_source = 'school' AND confirmed_by_admin_id IS NOT NULL
       AND confirmed_by_parent_id IS NULL)
      OR (confirmation_source = 'parent' AND confirmed_by_parent_id IS NOT NULL
          AND confirmed_by_admin_id IS NULL)
      OR (confirmation_source = 'guardian' AND confirmed_by_parent_id IS NULL
          AND confirmed_by_admin_id IS NULL AND parent_name_on_form IS NOT NULL)))
"""

WITHOUT_GUARDIAN = """
(status IN ('pending', 'not_sent') AND confirmation_source IS NULL
 AND confirmed_by_admin_id IS NULL AND confirmed_by_parent_id IS NULL
 AND confirmed_via IS NULL AND confirmed_at IS NULL)
OR
(status IN ('confirmed', 'withdrawn') AND confirmed_via IS NOT NULL AND confirmed_at IS NOT NULL
 AND ((confirmation_source = 'school' AND confirmed_by_admin_id IS NOT NULL
       AND confirmed_by_parent_id IS NULL)
      OR (confirmation_source = 'parent' AND confirmed_by_parent_id IS NOT NULL
          AND confirmed_by_admin_id IS NULL)))
"""


def upgrade() -> None:
    # Committed on its own: Postgres will not let a value added in a
    # transaction be used (here, in the constraint below) inside it.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE consent_confirmation_source ADD VALUE IF NOT EXISTS 'guardian'"
        )

    op.drop_constraint(op.f(CONSTRAINT), "consent_records", type_="check")
    op.create_check_constraint(
        "confirmation_fields_match_status", "consent_records", WITH_GUARDIAN
    )

    op.create_table(
        "guardian_invitations",
        sa.Column(
            "id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("contact", sa.String(255), nullable=False),
        sa.Column(
            "contact_method",
            postgresql.ENUM(name="parent_contact_method", create_type=False),
            nullable=False,
        ),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("send_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guardian_name", sa.String(255), nullable=True),
        sa.Column("guardian_contact", sa.String(255), nullable=True),
        sa.Column("guardian_relationship", sa.String(80), nullable=True),
        sa.CheckConstraint(
            "consented_at IS NULL OR guardian_name IS NOT NULL",
            name="consent_names_the_guardian",
        ),
    )
    op.create_index(
        "ix_guardian_invitations_student_created",
        "guardian_invitations",
        ["student_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_guardian_invitations_student_created", table_name="guardian_invitations")
    op.drop_table("guardian_invitations")
    op.execute(
        "UPDATE consent_records SET status = 'pending', confirmation_source = NULL, "
        "confirmed_via = NULL, confirmed_at = NULL WHERE confirmation_source = 'guardian'"
    )
    op.drop_constraint(op.f(CONSTRAINT), "consent_records", type_="check")
    op.create_check_constraint(
        "confirmation_fields_match_status", "consent_records", WITHOUT_GUARDIAN
    )
    # The enum value stays: Postgres cannot remove one, and nothing emits it.
