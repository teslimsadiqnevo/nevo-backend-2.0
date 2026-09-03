"""Resolve student onboarding, telemetry, and concept playback blockers.

Revision ID: 20260903_0040
Revises: 20260902_0039
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260903_0040"
down_revision: str | Sequence[str] | None = "20260902_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "student_onboarding_grants",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_student_onboarding_grants_token",
        "student_onboarding_grants",
        ["token_digest"],
        unique=True,
    )
    op.create_index(
        "ix_student_onboarding_grants_expiry",
        "student_onboarding_grants",
        ["expires_at"],
    )

    op.add_column("concepts", sa.Column("lesson_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_concepts_lesson_id_lessons",
        "concepts",
        "lessons",
        ["lesson_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_concepts_lesson_id", "concepts", ["lesson_id"])

    op.alter_column("lesson_sessions", "lesson_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column(
        "lesson_sessions",
        sa.Column("session_type", sa.String(length=24), server_default="lesson", nullable=False),
    )

    op.execute("UPDATE ai_prompt_templates SET active = false WHERE name = 'content_parse.default'")
    op.execute(
        """
        INSERT INTO ai_prompt_templates (
            service, name, version, system_template, user_template,
            required_variables, active
        )
        VALUES (
            'lesson_generation',
            'content_parse.default',
            2,
            'You parse teacher lesson sources into curriculum-agnostic structured segments. Return strict JSON only. Use warm functional learning language. Avoid prohibited learner labels.',
            'Parse lesson {lesson_title} from {source_type}. This is chunk {chunk_number} of {chunk_count}. Return a JSON object with a segments array. Each segment must include content_type, sequence_order, title, body, availableModalities, comprehension_checkpoints, optional text_variant, visual_variant, audio_variant, interactive_variant, calculation_variant, needs_review, and review_reasons. Every comprehension checkpoint must contain id, conceptName, prompt, answerType (single_choice, multiple_choice, text, numeric, or boolean), options as value-label objects, answerKey, explanation, and position. Every answerKey must be derivable from the supplied lesson source. Allowed content_type values are explanatory_text, visual_diagram, worked_example, practice_question, definition, summary, calculation. For every non-calculation segment, text is always available and at least one other genuinely useful modality should be present when possible. Use only visual, audio, text, interactive. If fewer than two modalities are genuinely appropriate, flag the segment for teacher review. For calculation segments, decompose into co_construction steps and set availableModalities to interactive and visual only. Include narrationAudio placeholders in each calculation step when a script can be written. Source follows. {source_text}',
            '["lesson_title","source_type","chunk_number","chunk_count","source_text"]'::jsonb,
            true
        )
        ON CONFLICT (name, version) DO UPDATE SET active = true
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM ai_prompt_templates WHERE name = 'content_parse.default' AND version = 2")
    op.execute(
        "UPDATE ai_prompt_templates SET active = true WHERE name = 'content_parse.default' AND version = 1"
    )
    op.drop_column("lesson_sessions", "session_type")
    op.alter_column("lesson_sessions", "lesson_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_index("ix_concepts_lesson_id", table_name="concepts")
    op.drop_constraint("fk_concepts_lesson_id_lessons", "concepts", type_="foreignkey")
    op.drop_column("concepts", "lesson_id")
    op.drop_index("ix_student_onboarding_grants_expiry", table_name="student_onboarding_grants")
    op.drop_index("uq_student_onboarding_grants_token", table_name="student_onboarding_grants")
    op.drop_table("student_onboarding_grants")
