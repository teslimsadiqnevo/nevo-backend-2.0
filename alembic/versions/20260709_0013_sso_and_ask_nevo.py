"""Add SSO roster sync and Ask Nevo logs.

Revision ID: 20260709_0013
Revises: 20260708_0012
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260709_0013"
down_revision: str | Sequence[str] | None = "20260708_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

sso_provider_enum = postgresql.ENUM("microsoft", "google", name="sso_provider", create_type=False)
roster_sync_status_enum = postgresql.ENUM(
    "completed",
    "partial_manual_review",
    "failed",
    name="roster_sync_status",
    create_type=False,
)
roster_sync_issue_status_enum = postgresql.ENUM(
    "open",
    "resolved",
    name="roster_sync_issue_status",
    create_type=False,
)
ask_nevo_role_enum = postgresql.ENUM(
    "student",
    "teacher",
    name="ask_nevo_role",
    create_type=False,
)
ask_nevo_question_category_enum = postgresql.ENUM(
    "lesson_help",
    "profile_pattern",
    "class_planning",
    "family_message",
    "flag_review",
    "general",
    name="ask_nevo_question_category",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    sso_provider_enum.create(bind, checkfirst=True)
    roster_sync_status_enum.create(bind, checkfirst=True)
    roster_sync_issue_status_enum.create(bind, checkfirst=True)
    ask_nevo_role_enum.create(bind, checkfirst=True)
    ask_nevo_question_category_enum.create(bind, checkfirst=True)

    op.create_table(
        "school_sso_configurations",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sso_provider_enum, nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column("hosted_domain", sa.String(length=255), nullable=True),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_secret_ref", sa.String(length=255), nullable=True),
        sa.Column("school_url_slug", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "uq_school_sso_configurations_school_provider",
        "school_sso_configurations",
        ["school_id", "provider"],
        unique=True,
    )
    op.create_index(
        "ix_school_sso_configurations_slug_provider",
        "school_sso_configurations",
        ["school_url_slug", "provider"],
    )

    op.create_table(
        "roster_sync_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sso_provider_enum, nullable=False),
        sa.Column("status", roster_sync_status_enum, nullable=False),
        sa.Column("imported_students", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_teachers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_teacher_class_mappings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_roster_sync_runs_school_started", "roster_sync_runs", ["school_id", "started_at"])
    op.create_index("ix_roster_sync_runs_provider_started", "roster_sync_runs", ["provider", "started_at"])

    op.create_table(
        "roster_sync_issues",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("roster_sync_run_id", sa.Uuid(), sa.ForeignKey("roster_sync_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", roster_sync_issue_status_enum, nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_roster_sync_issues_school_status", "roster_sync_issues", ["school_id", "status"])
    op.create_index("ix_roster_sync_issues_run", "roster_sync_issues", ["roster_sync_run_id"])

    op.create_table(
        "ask_nevo_interactions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("role", ask_nevo_role_enum, nullable=False),
        sa.Column("current_page", sa.String(length=120), nullable=False),
        sa.Column("context_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("question_category", ask_nevo_question_category_enum, nullable=False),
        sa.Column("ai_gateway_call_id", sa.Uuid(), sa.ForeignKey("ai_gateway_calls.id", ondelete="SET NULL"), nullable=True),
        sa.Column("response_helpful", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ask_nevo_interactions_actor_created", "ask_nevo_interactions", ["actor_user_id", "created_at"])
    op.create_index("ix_ask_nevo_interactions_role_created", "ask_nevo_interactions", ["role", "created_at"])
    op.create_index("ix_ask_nevo_interactions_category_created", "ask_nevo_interactions", ["question_category", "created_at"])

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
            '10000000-0000-4000-8000-000000000006',
            'narrative',
            'ask_nevo.student',
            1,
            'You are Ask Nevo for a student. Answer warmly, age-appropriately, '
            'and only from supplied lesson context. Never reveal raw learner '
            'profile data, confidence levels, or inference mechanics. Use '
            'functional learning language only.',
            'Student question:\\n{question}\\n\\nCurrent context JSON:\\n{context}',
            '["question", "context"]'::jsonb,
            true
        ),
        (
            '10000000-0000-4000-8000-000000000007',
            'narrative',
            'ask_nevo.teacher',
            1,
            'You are Ask Nevo for a teacher. Respond like a thoughtful '
            'colleague leaving a useful note. Be specific to supplied class, '
            'student, lesson, flag, or thread data whenever IDs are present. '
            'Use functional learning language only.',
            'Teacher question:\\n{question}\\n\\nDynamic teacher context JSON:\\n{context}',
            '["question", "context"]'::jsonb,
            true
        )
        ON CONFLICT (name, version) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM ai_prompt_templates WHERE name IN ('ask_nevo.student', 'ask_nevo.teacher')"
    )
    op.drop_index("ix_ask_nevo_interactions_category_created", table_name="ask_nevo_interactions")
    op.drop_index("ix_ask_nevo_interactions_role_created", table_name="ask_nevo_interactions")
    op.drop_index("ix_ask_nevo_interactions_actor_created", table_name="ask_nevo_interactions")
    op.drop_table("ask_nevo_interactions")
    op.drop_index("ix_roster_sync_issues_run", table_name="roster_sync_issues")
    op.drop_index("ix_roster_sync_issues_school_status", table_name="roster_sync_issues")
    op.drop_table("roster_sync_issues")
    op.drop_index("ix_roster_sync_runs_provider_started", table_name="roster_sync_runs")
    op.drop_index("ix_roster_sync_runs_school_started", table_name="roster_sync_runs")
    op.drop_table("roster_sync_runs")
    op.drop_index("ix_school_sso_configurations_slug_provider", table_name="school_sso_configurations")
    op.drop_index("uq_school_sso_configurations_school_provider", table_name="school_sso_configurations")
    op.drop_table("school_sso_configurations")
    ask_nevo_question_category_enum.drop(op.get_bind(), checkfirst=True)
    ask_nevo_role_enum.drop(op.get_bind(), checkfirst=True)
    roster_sync_issue_status_enum.drop(op.get_bind(), checkfirst=True)
    roster_sync_status_enum.drop(op.get_bind(), checkfirst=True)
    sso_provider_enum.drop(op.get_bind(), checkfirst=True)
