"""Add Claude routing and content parsing prompt library.

Revision ID: 20260824_0027
Revises: 20260824_0026
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260824_0027"
down_revision: str | Sequence[str] | None = "20260824_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PROMPT_NAMES = (
    "content_parse.lesson_boundaries",
    "content_parse.module_boundaries",
    "content_parse.segment_boundaries",
    "content_parse.module_recap",
    "content_parse.module_preview",
    "content_parse.boundary_confidence",
)


def upgrade() -> None:
    op.execute("ALTER TYPE ai_provider ADD VALUE IF NOT EXISTS 'claude'")
    op.get_bind().exec_driver_sql(
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
        VALUES
        (
            'lesson_generation',
            'content_parse.lesson_boundaries',
            1,
            'Identify lesson boundaries in teacher-provided Nigerian school content. Return strict JSON only. Use the source as the only factual authority. Use Zero-Tag, functional language only. Never rank learners.',
            'Input may be textbook pages, scheme-of-work text, teacher notes, OCR text from scans, or mixed formatting. Identify lesson boundaries and proposed lesson titles. Return exactly {"lessons":[{"title":"string","start_page":1,"end_page":1,"segment_hint_count":1}]}. Do not invent lessons beyond the source. If the block appears to exceed 40 pages or 15 lessons, return {"lessons":[],"error":"ceiling_exceeded"}. Source follows. {source_text}',
            '["source_text"]'::jsonb,
            true
        ),
        (
            'lesson_generation',
            'content_parse.module_boundaries',
            1,
            'Identify module boundaries inside one lesson. Return strict JSON only. Default to modules for lessons with six or more instructional segments. Use Zero-Tag, functional language only. Never split by easy/hard difficulty or learner ranking.',
            'Given this lesson and its segment list, propose module boundaries with short student-friendly titles. If there are fewer than six instructional segments, return {"modules":[]}. Return exactly {"modules":[{"title":"string","segment_indices":[0,1]}]}. Boundaries should follow concept shifts, worked examples, practice transitions, or recap-worthy clusters. Lesson follows. {lesson_text}',
            '["lesson_text"]'::jsonb,
            true
        ),
        (
            'lesson_generation',
            'content_parse.segment_boundaries',
            1,
            'Identify instructional segments within a module. Return strict JSON only. Use Zero-Tag, plain functional language. Never use patronising or ability-ranking language.',
            'Split the module into instructional segments with proposed titles and modality flags. Return exactly {"segments":[{"title":"string","modality":"text|visual|audio|interactive","content_range":"string"}]}. Choose modality from the content itself: explanation, diagram/table, narration-friendly prose, or practice interaction. Do not create easy/hard groups. Module follows. {module_text}',
            '["module_text"]'::jsonb,
            true
        ),
        (
            'lesson_generation',
            'content_parse.module_recap',
            1,
            'Write module recap text for a student. Return strict JSON only. Use warm, plain, non-patronising, Zero-Tag functional language.',
            'Write a 2-3 sentence recap for the completed module. Use only the supplied segment summaries. Return exactly {"recap":"string"}. Segments follow. {module_segments}',
            '["module_segments"]'::jsonb,
            true
        ),
        (
            'lesson_generation',
            'content_parse.module_preview',
            1,
            'Write module preview text for a student. Return strict JSON only. Use warm, plain, non-patronising, Zero-Tag functional language.',
            'Write a 1-2 sentence preview for the next module. Use only the supplied segment summaries. Return exactly {"preview":"string"}. Segments follow. {module_segments}',
            '["module_segments"]'::jsonb,
            true
        ),
        (
            'lesson_generation',
            'content_parse.boundary_confidence',
            1,
            'Judge whether a proposed lesson, module, or segment boundary is worth a teacher glance. Return strict JSON only. Never expose percentages, scores, or learner labels. Use Zero-Tag functional language.',
            'Review this proposed boundary against the nearby source. Return exactly {"confidence":"high|low","reason":"string"}. The reason must be short, plain, and suitable as an on-tap explanation for a teacher. Boundary: {boundary_json}. Source context: {source_context}',
            '["boundary_json","source_context"]'::jsonb,
            true
        )
        ON CONFLICT (name, version) DO NOTHING
        """
    )


def downgrade() -> None:
    quoted = ", ".join(f"'{name}'" for name in PROMPT_NAMES)
    op.execute(
        sa.text(
            f"""
            DELETE FROM ai_prompt_templates
            WHERE name IN ({quoted})
              AND version = 1
            """
        )
    )
