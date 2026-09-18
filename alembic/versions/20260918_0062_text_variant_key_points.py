"""Ask the parser for key points, which have never once been produced.

TextVariant has carried keyPoints since it was written and every segment in
the library has an empty list, because nothing asked for them. A field on the
contract that is always empty is the same trap the calculation answer was.

Revision ID: 20260918_0062
Revises: 20260918_0061
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260918_0062"
down_revision: str | Sequence[str] | None = "20260918_0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADDITION = (
    " Give each segment's text variant two to four keyPoints: the things a "
    "learner should still have with them after the segment, each a short "
    "phrase they could say back. They sit beside the body, so do not retell "
    "it - a point that repeats the whole segment is dropped. Do not send a "
    "body inside text_variant; the segment's own body is the text."
)

INSERT_INACTIVE = """
    INSERT INTO ai_prompt_templates (
        service, name, version, system_template, user_template,
        required_variables, active
    )
    SELECT service, name, version + 1, system_template || $tpl${addition}$tpl$,
           user_template, required_variables, false
    FROM ai_prompt_templates
    WHERE name = '{name}'
      AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = '{name}')
"""

STAND_DOWN = "UPDATE ai_prompt_templates SET active = false WHERE name = '{name}'"

RAISE_NEWEST = """
    UPDATE ai_prompt_templates SET active = true
    WHERE name = '{name}'
      AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = '{name}')
"""

DROP_NEWEST = """
    DELETE FROM ai_prompt_templates
    WHERE name = '{name}'
      AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = '{name}')
"""

NAME = "content_parse.default"


def upgrade() -> None:
    op.execute(INSERT_INACTIVE.format(name=NAME, addition=ADDITION))
    op.execute(STAND_DOWN.format(name=NAME))
    op.execute(RAISE_NEWEST.format(name=NAME))


def downgrade() -> None:
    op.execute(DROP_NEWEST.format(name=NAME))
    op.execute(RAISE_NEWEST.format(name=NAME))
