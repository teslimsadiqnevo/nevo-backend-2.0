"""Add Ask Nevo product intelligence signal event types.

Revision ID: 20260822_0024
Revises: 20260822_0023
Create Date: 2026-08-22 00:24:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260822_0024"
down_revision: str | None = "20260822_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

new_signal_event_values = (
    "ask_nevo_question_student",
    "ask_nevo_question_teacher",
    "ask_nevo_cannot_help",
    "ask_nevo_redirect_used",
)


def upgrade() -> None:
    for value in new_signal_event_values:
        op.execute(f"ALTER TYPE signal_event_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL enum values are intentionally not removed on downgrade.
    pass
