"""Add gaming detection schema (SCRUM-62, architecture only).

Schema and thresholds land now so the detection engine does not need a
retrofit later. No runtime path reads or writes these columns yet.

Revision ID: 20260812_0018
Revises: 20260808_0017
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260812_0018"
down_revision: str | Sequence[str] | None = "20260808_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

gaming_suspicion_level_enum = postgresql.ENUM(
    "none",
    "low",
    "moderate",
    "high",
    name="gaming_suspicion_level",
    create_type=False,
)
engagement_anomaly_type_enum = postgresql.ENUM(
    "response_time_slowdown",
    "error_rate_spike",
    "abandoned_attempt_spike",
    name="engagement_anomaly_type",
    create_type=False,
)
engagement_anomaly_scope_enum = postgresql.ENUM(
    "single_content_type",
    "all_content_types",
    name="engagement_anomaly_scope",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    gaming_suspicion_level_enum.create(bind, checkfirst=True)
    engagement_anomaly_type_enum.create(bind, checkfirst=True)
    engagement_anomaly_scope_enum.create(bind, checkfirst=True)

    op.add_column(
        "learner_profiles",
        sa.Column(
            "gaming_suspicion_level",
            gaming_suspicion_level_enum,
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "learner_profiles",
        sa.Column(
            "gaming_suspicion_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "learner_profiles",
        sa.Column(
            "gaming_anomaly_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "gaming_anomaly_count_nonnegative",
        "learner_profiles",
        "gaming_anomaly_count >= 0",
    )
    op.create_check_constraint(
        "gaming_suspicion_level_matches_timestamp",
        "learner_profiles",
        "(gaming_suspicion_level = 'none') = "
        "(gaming_suspicion_updated_at IS NULL)",
    )

    op.create_table(
        "learner_engagement_anomalies",
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
        sa.Column(
            "learner_profile_id",
            sa.Uuid(),
            sa.ForeignKey("learner_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "lesson_session_id",
            sa.Uuid(),
            sa.ForeignKey("lesson_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("anomaly_type", engagement_anomaly_type_enum, nullable=False),
        sa.Column("scope", engagement_anomaly_scope_enum, nullable=False),
        sa.Column("rule_key", sa.String(length=120), nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=False),
        sa.Column("observed_value", sa.Float(), nullable=False),
        sa.Column("deviation_ratio", sa.Float(), nullable=False),
        sa.Column("observation_count", sa.SmallInteger(), nullable=False),
        sa.Column("distinct_content_types", sa.SmallInteger(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "baseline_value >= 0 AND observed_value >= 0",
            name="anomaly_values_nonnegative",
        ),
        sa.CheckConstraint(
            "deviation_ratio > 0",
            name="deviation_ratio_positive",
        ),
        sa.CheckConstraint(
            "distinct_content_types >= 1 AND observation_count >= 1",
            name="anomaly_counts_positive",
        ),
    )
    op.create_index(
        "ix_learner_engagement_anomalies_student_detected",
        "learner_engagement_anomalies",
        ["student_id", "detected_at"],
    )
    op.create_index(
        "ix_learner_engagement_anomalies_rule_detected",
        "learner_engagement_anomalies",
        ["rule_key", "detected_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_learner_engagement_anomalies_rule_detected",
        table_name="learner_engagement_anomalies",
    )
    op.drop_index(
        "ix_learner_engagement_anomalies_student_detected",
        table_name="learner_engagement_anomalies",
    )
    op.drop_table("learner_engagement_anomalies")
    op.drop_constraint(
        op.f("ck_learner_profiles_gaming_suspicion_level_matches_timestamp"),
        "learner_profiles",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_learner_profiles_gaming_anomaly_count_nonnegative"),
        "learner_profiles",
        type_="check",
    )
    op.drop_column("learner_profiles", "gaming_anomaly_count")
    op.drop_column("learner_profiles", "gaming_suspicion_updated_at")
    op.drop_column("learner_profiles", "gaming_suspicion_level")
    engagement_anomaly_scope_enum.drop(op.get_bind(), checkfirst=True)
    engagement_anomaly_type_enum.drop(op.get_bind(), checkfirst=True)
    gaming_suspicion_level_enum.drop(op.get_bind(), checkfirst=True)
