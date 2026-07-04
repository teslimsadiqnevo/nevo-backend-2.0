"""Add centralized AI gateway prompts and telemetry.

Revision ID: 20260704_0007
Revises: 20260704_0006
Create Date: 2026-07-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260704_0007"
down_revision: str | Sequence[str] | None = "20260704_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ai_service_enum = postgresql.ENUM(
    "adaptation",
    "lesson_generation",
    "narrative",
    name="ai_service",
    create_type=False,
)
ai_call_status_enum = postgresql.ENUM(
    "succeeded",
    "fallback",
    "failed",
    name="ai_call_status",
    create_type=False,
)
ai_provider_enum = postgresql.ENUM(
    "gemini",
    "rule_based",
    name="ai_provider",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    ai_service_enum.create(bind, checkfirst=True)
    ai_call_status_enum.create(bind, checkfirst=True)
    ai_provider_enum.create(bind, checkfirst=True)

    op.create_table(
        "ai_prompt_templates",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("service", ai_service_enum, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("system_template", sa.Text(), nullable=False),
        sa.Column("user_template", sa.Text(), nullable=False),
        sa.Column(
            "required_variables",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "name",
            "version",
            name="uq_ai_prompt_templates_name_version",
        ),
    )
    op.create_index(
        "uq_ai_prompt_templates_active_name",
        "ai_prompt_templates",
        ["name"],
        unique=True,
        postgresql_where=sa.text("active"),
    )

    op.create_table(
        "ai_gateway_calls",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "requester_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "prompt_template_id",
            sa.Uuid(),
            sa.ForeignKey("ai_prompt_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("service", ai_service_enum, nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("provider", ai_provider_enum, nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("status", ai_call_status_enum, nullable=False),
        sa.Column(
            "input_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "output_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "thought_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(precision=14, scale=8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "compliance_retries",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "fallback_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 "
            "AND thought_tokens >= 0",
            name="token_counts_non_negative",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0 AND estimated_cost_usd >= 0",
            name="performance_values_non_negative",
        ),
        sa.CheckConstraint(
            "(status = 'fallback') = fallback_used",
            name="fallback_status_matches_flag",
        ),
    )
    op.create_index(
        "ix_ai_gateway_calls_service_created_at",
        "ai_gateway_calls",
        ["service", "created_at"],
    )
    op.create_index(
        "ix_ai_gateway_calls_school_created_at",
        "ai_gateway_calls",
        ["school_id", "created_at"],
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
        VALUES
        (
            '10000000-0000-4000-8000-000000000001',
            'adaptation',
            'adaptation.default',
            1,
            'Adapt the teacher-provided material without changing its facts. '
            'The source is the only factual authority. Use observable learning '
            'preferences and functional support only. Never infer learner labels.',
            'Teacher source:\\n{source_text}\\n\\nAdaptation request:\\n{instruction}',
            '["source_text", "instruction"]'::jsonb,
            true
        ),
        (
            '10000000-0000-4000-8000-000000000002',
            'lesson_generation',
            'lesson_generation.default',
            1,
            'Create a clear lesson from the teacher source. The source is the '
            'only factual authority: do not invent facts, objectives, examples, '
            'or claims not grounded in it. Preserve the teacher''s meaning.',
            'Teacher source:\\n{source_text}\\n\\nLearning goal:\\n{learning_goal}',
            '["source_text", "learning_goal"]'::jsonb,
            true
        ),
        (
            '10000000-0000-4000-8000-000000000003',
            'narrative',
            'narrative.default',
            1,
            'Summarize only the supplied educational evidence. Describe '
            'observable patterns, not inferred labels or causes.',
            'Evidence:\\n{evidence}',
            '["evidence"]'::jsonb,
            true
        )
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_gateway_calls_school_created_at",
        table_name="ai_gateway_calls",
    )
    op.drop_index(
        "ix_ai_gateway_calls_service_created_at",
        table_name="ai_gateway_calls",
    )
    op.drop_table("ai_gateway_calls")
    op.drop_index(
        "uq_ai_prompt_templates_active_name",
        table_name="ai_prompt_templates",
    )
    op.drop_table("ai_prompt_templates")
    ai_provider_enum.drop(op.get_bind(), checkfirst=True)
    ai_call_status_enum.drop(op.get_bind(), checkfirst=True)
    ai_service_enum.drop(op.get_bind(), checkfirst=True)
