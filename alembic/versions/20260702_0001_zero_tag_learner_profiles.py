"""Create Zero-Tag learner profile tables.

Revision ID: 20260702_0001
Revises:
Create Date: 2026-07-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260702_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

confidence_values = ("low", "medium", "high")
channel_values = (
    "visual",
    "auditory",
    "textual",
    "interactive",
    "multimodal",
    "undetermined",
)
change_source_values = (
    "system_inference",
    "educator_review",
    "learner_input",
    "roster_import",
    "correction",
)

confidence_enum = postgresql.ENUM(
    *confidence_values,
    name="profile_confidence",
    create_type=False,
)
channel_enum = postgresql.ENUM(
    *channel_values,
    name="processing_channel_preference",
    create_type=False,
)
change_source_enum = postgresql.ENUM(
    *change_source_values,
    name="profile_change_source",
    create_type=False,
)


def dimension_columns() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "processing_channel_preference",
            channel_enum,
            nullable=False,
            server_default="undetermined",
        ),
        sa.Column(
            "processing_channel_preference_confidence",
            confidence_enum,
            nullable=False,
            server_default="low",
        ),
        sa.Column("cognitive_load_threshold", sa.SmallInteger(), nullable=True),
        sa.Column(
            "cognitive_load_threshold_confidence",
            confidence_enum,
            nullable=False,
            server_default="low",
        ),
        sa.Column("processing_speed", sa.SmallInteger(), nullable=True),
        sa.Column(
            "processing_speed_confidence",
            confidence_enum,
            nullable=False,
            server_default="low",
        ),
        sa.Column("working_memory_capacity", sa.SmallInteger(), nullable=True),
        sa.Column(
            "working_memory_capacity_confidence",
            confidence_enum,
            nullable=False,
            server_default="low",
        ),
        sa.Column("attention_span", sa.SmallInteger(), nullable=True),
        sa.Column(
            "attention_span_confidence",
            confidence_enum,
            nullable=False,
            server_default="low",
        ),
        sa.Column("performance_sensitivity", sa.SmallInteger(), nullable=True),
        sa.Column(
            "performance_sensitivity_confidence",
            confidence_enum,
            nullable=False,
            server_default="low",
        ),
    ]


def dimension_checks() -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint(
            "cognitive_load_threshold IS NULL OR cognitive_load_threshold BETWEEN 1 AND 5",
            name="cognitive_load_threshold_range",
        ),
        sa.CheckConstraint(
            "processing_speed IS NULL OR processing_speed BETWEEN 1 AND 5",
            name="processing_speed_range",
        ),
        sa.CheckConstraint(
            "working_memory_capacity IS NULL OR working_memory_capacity BETWEEN 1 AND 5",
            name="working_memory_capacity_range",
        ),
        sa.CheckConstraint(
            "attention_span IS NULL OR attention_span BETWEEN 1 AND 240",
            name="attention_span_range",
        ),
        sa.CheckConstraint(
            "performance_sensitivity IS NULL OR performance_sensitivity BETWEEN 1 AND 5",
            name="performance_sensitivity_range",
        ),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    bind = op.get_bind()
    confidence_enum.create(bind, checkfirst=True)
    channel_enum.create(bind, checkfirst=True)
    change_source_enum.create(bind, checkfirst=True)

    op.create_table(
        "learner_profiles",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("learner_id", sa.Uuid(), nullable=False),
        *dimension_columns(),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "observed_event_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *dimension_checks(),
        sa.CheckConstraint(
            "version > 0",
            name="version_positive",
        ),
        sa.CheckConstraint(
            "observed_event_count >= 0",
            name="observed_event_count_nonnegative",
        ),
        sa.UniqueConstraint(
            "learner_id",
            name="uq_learner_profiles_learner_id",
        ),
    )

    op.create_table(
        "learner_profile_history",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "learner_profile_id",
            sa.Uuid(),
            sa.ForeignKey(
                "learner_profiles.id",
                name="fk_learner_profile_history_profile",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("learner_id", sa.Uuid(), nullable=False),
        *dimension_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("observed_event_count", sa.Integer(), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("change_source", change_source_enum, nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.Column("change_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *dimension_checks(),
        sa.CheckConstraint(
            "version > 0",
            name="version_positive",
        ),
        sa.CheckConstraint(
            "observed_event_count >= 0",
            name="observed_event_count_nonnegative",
        ),
        sa.UniqueConstraint(
            "learner_profile_id",
            "version",
            name="uq_learner_profile_history_profile_version",
        ),
    )
    op.create_index(
        "ix_learner_profile_history_learner_created",
        "learner_profile_history",
        ["learner_id", "created_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_learner_profile_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'learner profile history is immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_learner_profile_history_immutable
        BEFORE UPDATE OR DELETE ON learner_profile_history
        FOR EACH ROW
        EXECUTE FUNCTION prevent_learner_profile_history_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_learner_profile_history_immutable ON learner_profile_history"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_learner_profile_history_mutation")
    op.drop_index(
        "ix_learner_profile_history_learner_created",
        table_name="learner_profile_history",
    )
    op.drop_table("learner_profile_history")
    op.drop_table("learner_profiles")

    bind = op.get_bind()
    change_source_enum.drop(bind, checkfirst=True)
    channel_enum.drop(bind, checkfirst=True)
    confidence_enum.drop(bind, checkfirst=True)
