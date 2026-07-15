"""Add attention flags and intervention recommendations.

Revision ID: 20260708_0012
Revises: 20260707_0011
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260708_0012"
down_revision: str | Sequence[str] | None = "20260707_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

attention_flag_type_enum = postgresql.ENUM(
    "engagement_decline",
    "sudden_change",
    name="attention_flag_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    attention_flag_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "attention_flags",
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
        sa.Column("flag_type", attention_flag_type_enum, nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "acknowledged_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_attention_flags_student_generated",
        "attention_flags",
        ["student_id", "generated_at"],
    )
    op.create_index(
        "ix_attention_flags_type_generated",
        "attention_flags",
        ["flag_type", "generated_at"],
    )
    op.create_index(
        "ix_attention_flags_open_student",
        "attention_flags",
        ["student_id"],
        postgresql_where=sa.text("acknowledged_at IS NULL"),
    )

    op.create_table(
        "escalations",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "attention_flag_id",
            sa.Uuid(),
            sa.ForeignKey("attention_flags.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "teacher_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("teacher_note", sa.Text(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "acknowledged_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_escalations_student_generated",
        "escalations",
        ["student_id", "generated_at"],
    )
    op.create_index(
        "ix_escalations_teacher_generated",
        "escalations",
        ["teacher_id", "generated_at"],
    )
    op.create_index(
        "ix_escalations_unacknowledged_student",
        "escalations",
        ["student_id"],
        postgresql_where=sa.text("acknowledged_at IS NULL"),
    )

    op.create_table(
        "intervention_recommendations",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "attention_flag_id",
            sa.Uuid(),
            sa.ForeignKey("attention_flags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("recommendation_text", sa.Text(), nullable=False),
        sa.Column(
            "ai_gateway_call_id",
            sa.Uuid(),
            sa.ForeignKey("ai_gateway_calls.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_intervention_recommendations_student_generated",
        "intervention_recommendations",
        ["student_id", "generated_at"],
    )
    op.create_index(
        "ix_intervention_recommendations_flag_generated",
        "intervention_recommendations",
        ["attention_flag_id", "generated_at"],
    )

    op.execute(
        """
        INSERT INTO ai_prompt_templates (
            id,
            service,
            name,
            version,
            system_template,
            user_template,
            required_variables,
            active
        )
        VALUES (
            '10000000-0000-4000-8000-000000000005',
            'narrative',
            'intervention_recommendation.default',
            1,
            'Generate concise, practical classroom intervention suggestions '
            'from the supplied engagement flag context. Use functional, '
            'observable learning language only. Do not infer labels or causes.',
            'Attention flag context JSON:\\n{flag_context}\\n\\nReturn JSON '
            'with shape {{"recommendation_text":"2-4 actionable teacher '
            'steps grounded in the context"}}.',
            '["flag_context"]'::jsonb,
            true
        )
        ON CONFLICT (name, version) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM ai_prompt_templates
        WHERE id = '10000000-0000-4000-8000-000000000005'
           OR name = 'intervention_recommendation.default'
        """
    )
    op.drop_index(
        "ix_intervention_recommendations_flag_generated",
        table_name="intervention_recommendations",
    )
    op.drop_index(
        "ix_intervention_recommendations_student_generated",
        table_name="intervention_recommendations",
    )
    op.drop_table("intervention_recommendations")
    op.drop_index(
        "ix_escalations_unacknowledged_student",
        table_name="escalations",
    )
    op.drop_index("ix_escalations_teacher_generated", table_name="escalations")
    op.drop_index("ix_escalations_student_generated", table_name="escalations")
    op.drop_table("escalations")
    op.drop_index("ix_attention_flags_open_student", table_name="attention_flags")
    op.drop_index("ix_attention_flags_type_generated", table_name="attention_flags")
    op.drop_index(
        "ix_attention_flags_student_generated",
        table_name="attention_flags",
    )
    op.drop_table("attention_flags")
    attention_flag_type_enum.drop(op.get_bind(), checkfirst=True)
