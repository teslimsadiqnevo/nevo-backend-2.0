"""Add high-volume learner signal events.

Revision ID: 20260705_0008
Revises: 20260704_0007
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260705_0008"
down_revision: str | Sequence[str] | None = "20260704_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

signal_event_type_enum = postgresql.ENUM(
    "time_on_segment",
    "replay",
    "scroll",
    "simplify_trigger",
    "expand_trigger",
    "slower_trigger",
    "comprehension_response",
    "exit_attempt",
    "break_suggested",
    "break_taken",
    "engagement_signal",
    name="signal_event_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    signal_event_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "signal_events",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", signal_event_type_enum, nullable=False),
        sa.Column(
            "event_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_signal_events_student_session",
        "signal_events",
        ["student_id", "session_id"],
    )
    op.create_index(
        "ix_signal_events_student_timestamp",
        "signal_events",
        ["student_id", "timestamp"],
    )
    op.create_index(
        "ix_signal_events_type_timestamp",
        "signal_events",
        ["event_type", "timestamp"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_signal_events_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'signal_events rows are append-only';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER signal_events_append_only
        BEFORE UPDATE OR DELETE ON signal_events
        FOR EACH ROW
        EXECUTE FUNCTION prevent_signal_events_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS signal_events_append_only ON signal_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_signal_events_mutation")
    op.drop_index(
        "ix_signal_events_type_timestamp",
        table_name="signal_events",
    )
    op.drop_index(
        "ix_signal_events_student_timestamp",
        table_name="signal_events",
    )
    op.drop_index(
        "ix_signal_events_student_session",
        table_name="signal_events",
    )
    op.drop_table("signal_events")
    signal_event_type_enum.drop(op.get_bind(), checkfirst=True)

