"""A consent record says who consented, not who typed it in.

Where a school confirmed on a parent's behalf, the record stored the school
administrator, so it did not identify the consenting party at all. The paper
route makes that worse if it is not fixed first, because paper is exactly the
case where the school is the one at the keyboard.

Revision ID: 20260921_0067
Revises: 20260921_0066
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260921_0067"
down_revision: str | Sequence[str] | None = "20260921_0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "consent_records",
        sa.Column("parent_name_on_form", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "consent_records",
        sa.Column("parent_relationship", sa.String(length=80), nullable=True),
    )
    op.add_column("consent_records", sa.Column("signed_on", sa.Date(), nullable=True))
    op.add_column(
        "consent_records",
        sa.Column("notice_version", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "consent_records",
        sa.Column("evidence_storage_path", sa.Text(), nullable=True),
    )
    op.add_column("consent_records", sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=True))
    op.add_column(
        "consent_records",
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_consent_records_uploaded_by",
        "consent_records",
        "users",
        ["uploaded_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Written consent without the parent named is the gap this closes, so the
    # database is what holds it shut. Rows already recorded as written are
    # left alone: the constraint is NOT VALID until they are completed, since
    # inventing a parent's name to satisfy a check would be a false record.
    op.execute(
        """
        ALTER TABLE consent_records
        ADD CONSTRAINT ck_consent_records_written_consent_identifies_the_parent
        CHECK (
            confirmed_via <> 'written'
            OR (parent_name_on_form IS NOT NULL
                AND signed_on IS NOT NULL
                AND notice_version IS NOT NULL)
        ) NOT VALID
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_consent_records_written_consent_identifies_the_parent",
        "consent_records",
        type_="check",
    )
    op.drop_constraint("fk_consent_records_uploaded_by", "consent_records", type_="foreignkey")
    op.drop_column("consent_records", "uploaded_at")
    op.drop_column("consent_records", "uploaded_by_user_id")
    op.drop_column("consent_records", "evidence_storage_path")
    op.drop_column("consent_records", "notice_version")
    op.drop_column("consent_records", "signed_on")
    op.drop_column("consent_records", "parent_relationship")
    op.drop_column("consent_records", "parent_name_on_form")
