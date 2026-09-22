"""Store the simpler and the longer version of each lesson segment.

The adaptation engine has returned ``simplify`` and ``expand`` since it was
built, and nothing stood behind either word: the client got an instruction and
the one body of text the teacher uploaded. This adds the column those two
actions read from, and the prompt that writes it at parse time.

Additive and nullable. Every lesson already parsed keeps working - a null
means no rewrite exists and the client falls back to the body, which is what
it does today.

Revision ID: 20260922_0075
Revises: 20260921_0074
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260922_0075"
down_revision: str | Sequence[str] | None = "20260921_0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROMPT_NAME = "lesson_depth.default"

SYSTEM_TEMPLATE = (
    "You rewrite one segment of a Nigerian school lesson at two depths, for a "
    "learner who is partway through it.\n\n"
    "Return only a JSON object with exactly two string keys:\n"
    '  "simplified": the same content in plainer language, shorter, for a '
    "learner who has just shown they are struggling with it.\n"
    '  "expanded": the same content with more worked detail, longer, for a '
    "learner who has shown they have understood it and can take more.\n\n"
    "Rules, all of them absolute:\n"
    "- Teach the same thing. Do not add a fact, a figure, a name or an "
    "example that is not in the segment you were given. Every number you "
    "write must appear in that segment.\n"
    "- Do not remove anything the learner is assessed on. Simpler means "
    "plainer sentences and fewer clauses, not less of the lesson.\n"
    "- Keep the register of a Nigerian classroom and the spellings already "
    "used. Do not localise, rename or substitute examples.\n"
    "- Address the learner directly, as the segment does. No preamble, no "
    "sign-off, no mention of simplifying or expanding.\n"
    "- Never mention the learner, their ability, their pace, or any reason "
    "they might be reading this version rather than the other.\n"
    "- No markdown fences. The whole answer is the JSON object."
)

#: ``str.format_map`` renders these, so placeholders are single-braced and a
#: stray brace anywhere in either template would fail the render.
USER_TEMPLATE = "Segment title: {title}\n\nSegment:\n{body}"

INSERT = """
    INSERT INTO ai_prompt_templates (
        service, name, version, system_template, user_template,
        required_variables, active
    )
    VALUES (
        'lesson_generation', '{name}', 1, $tpl${system}$tpl$, $tpl${user}$tpl$,
        '["title", "body"]'::jsonb, true
    )
    ON CONFLICT (name, version) DO UPDATE
        SET system_template = EXCLUDED.system_template,
            user_template = EXCLUDED.user_template,
            active = true
"""


def upgrade() -> None:
    op.add_column(
        "lesson_segments",
        sa.Column("depth_variants", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(INSERT.format(name=PROMPT_NAME, system=SYSTEM_TEMPLATE, user=USER_TEMPLATE))


def downgrade() -> None:
    op.execute(f"DELETE FROM ai_prompt_templates WHERE name = '{PROMPT_NAME}'")
    op.drop_column("lesson_segments", "depth_variants")
