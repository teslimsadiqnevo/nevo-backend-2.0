"""Add content parsing lessons and segments."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260710_0014"
down_revision: str | None = "20260709_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


lesson_source_type = postgresql.ENUM(
    "pdf",
    "word",
    "powerpoint",
    "google_drive",
    "onedrive",
    "text",
    name="lesson_source_type",
)
content_parse_status = postgresql.ENUM(
    "pending",
    "processing",
    "completed",
    "completed_with_review",
    "failed",
    name="content_parse_status",
)
lesson_content_type = postgresql.ENUM(
    "explanatory_text",
    "visual_diagram",
    "worked_example",
    "practice_question",
    "definition",
    "summary",
    "calculation",
    name="lesson_content_type",
)


def upgrade() -> None:
    bind = op.get_bind()
    lesson_source_type.create(bind, checkfirst=True)
    content_parse_status.create(bind, checkfirst=True)
    lesson_content_type.create(bind, checkfirst=True)

    op.create_table(
        "lessons",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("school_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_type", lesson_source_type, nullable=False),
        sa.Column(
            "source_reference",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "parser_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "status",
            content_parse_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "segment_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "review_segment_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("confirmation_summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "segment_count >= 0 AND review_segment_count >= 0",
            name=op.f("ck_lessons_lesson_segment_counts_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_lessons_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f("fk_lessons_school_id_schools"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lessons")),
    )
    op.create_index(
        "ix_lessons_created_by_created_at",
        "lessons",
        ["created_by_user_id", "created_at"],
    )
    op.create_index(
        "ix_lessons_school_created_at",
        "lessons",
        ["school_id", "created_at"],
    )

    op.create_table(
        "content_parse_runs",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            content_parse_status,
            server_default="processing",
            nullable=False,
        ),
        sa.Column("source_type", lesson_source_type, nullable=False),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "chunk_count",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "gemini_call_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "calculation_segment_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "tts_call_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "review_notes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "chunk_count >= 1 AND gemini_call_count >= 0 "
            "AND calculation_segment_count >= 0 AND tts_call_count >= 0",
            name=op.f("ck_content_parse_runs_content_parse_run_counts_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["lessons.id"],
            name=op.f("fk_content_parse_runs_lesson_id_lessons"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_content_parse_runs_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_parse_runs")),
    )
    op.create_index(
        "ix_content_parse_runs_lesson_created_at",
        "content_parse_runs",
        ["lesson_id", "created_at"],
    )
    op.create_index(
        "ix_content_parse_runs_status_created_at",
        "content_parse_runs",
        ["status", "created_at"],
    )

    op.create_table(
        "lesson_segments",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("parse_run_id", sa.Uuid(), nullable=False),
        sa.Column("segment_key", sa.String(length=120), nullable=False),
        sa.Column("content_type", lesson_content_type, nullable=False),
        sa.Column("sequence_order", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "available_modalities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "comprehension_checkpoints",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("text_variant", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "visual_variant",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "audio_variant",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "interactive_variant",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "calculation_variant",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "needs_review",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "review_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence_order >= 1",
            name=op.f("ck_lesson_segments_sequence_order_positive"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(available_modalities) >= 1",
            name=op.f("ck_lesson_segments_available_modalities_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["lessons.id"],
            name=op.f("fk_lesson_segments_lesson_id_lessons"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parse_run_id"],
            ["content_parse_runs.id"],
            name=op.f("fk_lesson_segments_parse_run_id_content_parse_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lesson_segments")),
    )
    op.create_index(
        "ix_lesson_segments_lesson_sequence_order",
        "lesson_segments",
        ["lesson_id", "sequence_order"],
        unique=True,
    )
    op.create_index(
        "ix_lesson_segments_lesson_content_type",
        "lesson_segments",
        ["lesson_id", "content_type"],
    )
    op.create_index(
        "ix_lesson_segments_needs_review",
        "lesson_segments",
        ["lesson_id", "needs_review"],
        postgresql_where=sa.text("needs_review = true"),
    )

    op.execute(
        """
        INSERT INTO ai_prompt_templates (
            service,
            name,
            version,
            system_template,
            user_template,
            required_variables,
            active
        )
        VALUES (
            'lesson_generation',
            'content_parse.default',
            1,
            'You parse teacher lesson sources into curriculum-agnostic structured segments. Return strict JSON only. Use warm functional learning language. Avoid prohibited learner labels.',
            'Parse lesson {lesson_title} from {source_type}. This is chunk {chunk_number} of {chunk_count}. Return a JSON object with a segments array. Each segment must include content_type, sequence_order, title, body, availableModalities, comprehension_checkpoints, optional text_variant, visual_variant, audio_variant, interactive_variant, calculation_variant, needs_review, and review_reasons. Allowed content_type values are explanatory_text, visual_diagram, worked_example, practice_question, definition, summary, calculation. For every non-calculation segment, text is always available and at least one other genuinely useful modality should be present when possible. Use only visual, audio, text, interactive. If fewer than two modalities are genuinely appropriate, flag the segment for teacher review. For calculation segments, decompose into co_construction steps and set availableModalities to interactive and visual only. Include narrationAudio placeholders in each calculation step when a script can be written. Source follows. {source_text}',
            '["lesson_title","source_type","chunk_number","chunk_count","source_text"]'::jsonb,
            true
        )
        ON CONFLICT (name, version) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM ai_prompt_templates
        WHERE name = 'content_parse.default'
          AND version = 1
        """
    )
    op.drop_index(
        "ix_lesson_segments_needs_review",
        table_name="lesson_segments",
        postgresql_where=sa.text("needs_review = true"),
    )
    op.drop_index(
        "ix_lesson_segments_lesson_content_type",
        table_name="lesson_segments",
    )
    op.drop_index(
        "ix_lesson_segments_lesson_sequence_order",
        table_name="lesson_segments",
    )
    op.drop_table("lesson_segments")
    op.drop_index(
        "ix_content_parse_runs_status_created_at",
        table_name="content_parse_runs",
    )
    op.drop_index(
        "ix_content_parse_runs_lesson_created_at",
        table_name="content_parse_runs",
    )
    op.drop_table("content_parse_runs")
    op.drop_index("ix_lessons_school_created_at", table_name="lessons")
    op.drop_index("ix_lessons_created_by_created_at", table_name="lessons")
    op.drop_table("lessons")
    lesson_content_type.drop(op.get_bind(), checkfirst=True)
    content_parse_status.drop(op.get_bind(), checkfirst=True)
    lesson_source_type.drop(op.get_bind(), checkfirst=True)
