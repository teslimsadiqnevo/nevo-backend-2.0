"""Add four-channel profile dimensions and inference signals.

Revision ID: 20260706_0010
Revises: 20260705_0009
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260706_0010"
down_revision: str | Sequence[str] | None = "20260705_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

channel_strength_enum = postgresql.ENUM(
    "low",
    "moderate",
    "strong",
    name="channel_preference_strength",
    create_type=False,
)

channel_dimensions = (
    "visual_spatial_preference",
    "auditory_preference",
    "reading_writing_preference",
    "interactive_kinesthetic_preference",
)

new_signal_event_values = (
    "calculation_step_response",
    "calculation_complete",
    "narration_played",
    "narration_replayed",
    "manipulative_piece_placed",
)


def upgrade() -> None:
    bind = op.get_bind()
    channel_strength_enum.create(bind, checkfirst=True)

    for value in new_signal_event_values:
        op.execute(f"ALTER TYPE signal_event_type ADD VALUE IF NOT EXISTS '{value}'")

    for table_name in ("learner_profiles", "learner_profile_history"):
        for dimension in channel_dimensions:
            op.add_column(
                table_name,
                sa.Column(
                    dimension,
                    channel_strength_enum,
                    nullable=True,
                ),
            )
            op.add_column(
                table_name,
                sa.Column(
                    f"{dimension}_confidence",
                    postgresql.ENUM(
                        "low",
                        "medium",
                        "high",
                        name="profile_confidence",
                        create_type=False,
                    ),
                    nullable=False,
                    server_default="low",
                ),
            )


def downgrade() -> None:
    for table_name in ("learner_profile_history", "learner_profiles"):
        for dimension in reversed(channel_dimensions):
            op.drop_column(table_name, f"{dimension}_confidence")
            op.drop_column(table_name, dimension)

    channel_strength_enum.drop(op.get_bind(), checkfirst=True)

