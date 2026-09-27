"""Persist student answers and typed preview/profile fields.

Revision ID: 20260927_0082
Revises: 20260927_0081
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260927_0082"
down_revision: str | Sequence[str] | None = "20260927_0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTENT_PROMPT = "content_parse.default"
ASK_PROMPTS = ("ask_nevo.student", "ask_nevo.teacher", "ask_nevo.parent")


def _copy_prompt(name: str, addition: str) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO ai_prompt_templates (
                service, name, version, system_template, user_template,
                required_variables, active
            )
            SELECT service, name, version + 1, system_template || :addition,
                   user_template, required_variables, false
            FROM ai_prompt_templates
            WHERE name = :name
              AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = :name)
            """
        ).bindparams(name=name, addition=addition)
    )
    op.execute(
        sa.text("UPDATE ai_prompt_templates SET active = false WHERE name = :name").bindparams(
            name=name
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE ai_prompt_templates SET active = true
            WHERE name = :name
              AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = :name)
            """
        ).bindparams(name=name)
    )


def upgrade() -> None:
    op.add_column("lessons", sa.Column("description", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE lessons AS lesson
        SET description = (
            SELECT left(regexp_replace(segment.body, '\\s+', ' ', 'g'), 240)
            FROM lesson_segments
            AS segment
            WHERE segment.lesson_id = lesson.id
            ORDER BY sequence_order
            LIMIT 1
        )
        WHERE lesson.description IS NULL
        """
    )
    op.add_column("users", sa.Column("avatar_tone", sa.String(length=40), nullable=True))
    op.execute(
        """
        UPDATE users
        SET avatar_tone = left(preferences ->> 'avatarTone', 40)
        WHERE preferences ? 'avatarTone'
          AND nullif(trim(preferences ->> 'avatarTone'), '') IS NOT NULL
        """
    )
    op.create_table(
        "lesson_question_attempts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.String(length=160), nullable=False),
        sa.Column("segment_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("client_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("question_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("attempt_number >= 1", name="lesson_question_attempt_number_positive"),
        sa.CheckConstraint(
            "source IN ('checkpoint', 'assessment')",
            name="lesson_question_attempt_source_valid",
        ),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["lesson_segments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["lesson_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_attempt_id", name="uq_lesson_question_attempt_client_id"),
        sa.UniqueConstraint(
            "session_id",
            "question_id",
            "attempt_number",
            name="uq_lesson_question_attempt_session_question_number",
        ),
    )
    op.create_index(
        "ix_lesson_question_attempts_student_lesson_submitted",
        "lesson_question_attempts",
        ["student_id", "lesson_id", "submitted_at"],
    )
    _copy_prompt(
        CONTENT_PROMPT,
        " Return a description field at lesson level: one short, plain-language "
        "sentence telling a learner what this lesson covers. Do not describe the "
        "parsing process.",
    )
    for name in ASK_PROMPTS:
        _copy_prompt(
            name,
            " If the question is outside Ask Nevo's educational and product-support "
            "scope, begin the response with exactly [[CANNOT_HELP]], then give a warm, "
            "brief handoff. Never use that marker when you can answer safely.",
        )


def downgrade() -> None:
    for name in (*ASK_PROMPTS, CONTENT_PROMPT):
        op.execute(
            sa.text(
                """
                DELETE FROM ai_prompt_templates
                WHERE name = :name
                  AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = :name)
                """
            ).bindparams(name=name)
        )
        op.execute(
            sa.text(
                """
                UPDATE ai_prompt_templates SET active = true
                WHERE name = :name
                  AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = :name)
                """
            ).bindparams(name=name)
        )
    op.drop_index(
        "ix_lesson_question_attempts_student_lesson_submitted",
        table_name="lesson_question_attempts",
    )
    op.drop_table("lesson_question_attempts")
    op.drop_column("users", "avatar_tone")
    op.drop_column("lessons", "description")
