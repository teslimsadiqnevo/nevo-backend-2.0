"""Add post-lesson profile update support.

Revision ID: 20260707_0011
Revises: 20260706_0010
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260707_0011"
down_revision: str | Sequence[str] | None = "20260706_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

attention_flag_status_enum = postgresql.ENUM(
    "open",
    "reviewed",
    "dismissed",
    name="profile_attention_flag_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    attention_flag_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "learner_profile_attention_flags",
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
            "lesson_session_id",
            sa.Uuid(),
            sa.ForeignKey("lesson_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "learner_profile_id",
            sa.Uuid(),
            sa.ForeignKey("learner_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("dimension", sa.String(length=120), nullable=False),
        sa.Column("current_value", sa.String(length=120), nullable=True),
        sa.Column("recommended_value", sa.String(length=120), nullable=True),
        sa.Column("rationale", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            attention_flag_status_enum,
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_learner_profile_attention_flags_student_created",
        "learner_profile_attention_flags",
        ["student_id", "created_at"],
    )
    op.create_index(
        "ix_learner_profile_attention_flags_status_created",
        "learner_profile_attention_flags",
        ["status", "created_at"],
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
            '10000000-0000-4000-8000-000000000004',
            'narrative',
            'profile_update.default',
            1,
            'Update learner profile dimensions only from the supplied lesson '
            'signals and current profile. Return strict JSON only. Use '
            'observable learning behavior and functional support terms. Never '
            'infer labels, causes, or traits outside the provided schema.',
            'Current profile JSON:\\n{current_profile}\\n\\nSession signal '
            'summary JSON:\\n{session_summary}\\n\\nReturn JSON with shape '
            '{{"updates":[{{"dimension":"cognitive_load_threshold",'
            '"value"\\:3,"confidence":"medium","rationale":"brief evidence"}}],'
            '"rationale":"brief overall reason"}}. Only include dimensions '
            'with enough evidence to change or increase confidence.',
            '["current_profile", "session_summary"]'::jsonb,
            true
        )
        ON CONFLICT (name, version) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM ai_prompt_templates
        WHERE id = '10000000-0000-4000-8000-000000000004'
           OR name = 'profile_update.default'
        """
    )
    op.drop_index(
        "ix_learner_profile_attention_flags_status_created",
        table_name="learner_profile_attention_flags",
    )
    op.drop_index(
        "ix_learner_profile_attention_flags_student_created",
        table_name="learner_profile_attention_flags",
    )
    op.drop_table("learner_profile_attention_flags")
    attention_flag_status_enum.drop(op.get_bind(), checkfirst=True)
