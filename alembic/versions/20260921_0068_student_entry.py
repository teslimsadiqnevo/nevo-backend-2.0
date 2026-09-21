"""A child's link names the child, and the roster carries their date of birth.

Entry asked a child to type back their own name and age, which the school had
already given us. Age is now derived from the roster, and the link resolves to
a person instead of to a class.

Revision ID: 20260921_0068
Revises: 20260921_0067
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260921_0068"
down_revision: str | Sequence[str] | None = "20260921_0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("date_of_birth", sa.Date(), nullable=True))
    op.add_column(
        "student_onboarding_grants",
        sa.Column("student_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_student_onboarding_grants_student",
        "student_onboarding_grants",
        "users",
        ["student_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_student_onboarding_grants_student",
        "student_onboarding_grants",
        ["student_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_student_onboarding_grants_student",
        table_name="student_onboarding_grants",
    )
    op.drop_constraint(
        "fk_student_onboarding_grants_student",
        "student_onboarding_grants",
        type_="foreignkey",
    )
    op.drop_column("student_onboarding_grants", "student_id")
    op.drop_column("users", "date_of_birth")
