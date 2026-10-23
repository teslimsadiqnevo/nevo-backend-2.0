"""Categorize concept-support notifications as attention.

Revision ID: 20261023_0118
Revises: 20261023_0117
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261023_0118"
down_revision: str | Sequence[str] | None = "20261023_0117"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE notifications
        SET category = 'attention'
        WHERE type = 'concept_support_needed'
          AND category IS DISTINCT FROM 'attention'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE notifications
        SET category = 'general'
        WHERE type = 'concept_support_needed'
          AND category = 'attention'
        """
    )
