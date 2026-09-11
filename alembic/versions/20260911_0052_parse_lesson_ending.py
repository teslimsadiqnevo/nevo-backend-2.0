"""Ask the parser for the lesson's ending and the calculation answer.

Revision ID: 20260911_0052
Revises: 20260911_0051
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260911_0052"
down_revision: str | Sequence[str] | None = "20260911_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADDITION = (
    " Alongside segments, return recap: two or three sentences addressed to "
    "the learner about what they have just worked through, in the second "
    "person and without praise for its own sake. Also return assessment: two "
    "to four closing questions in the same shape as a comprehension "
    "checkpoint, each with conceptName, prompt, answerType, at least two "
    "value-label options, answerKey and explanation. Draw them from across "
    "the whole lesson rather than repeating one segment's checkpoint, and "
    "every answerKey must be supported by the supplied source. For a "
    "calculation segment, the calculation variant must also carry answer: "
    "what the whole problem comes to, which is what the learner is marked "
    "against."
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

NAME = "content_parse.default"


def upgrade() -> None:
    op.execute(INSERT_INACTIVE.format(name=NAME, addition=ADDITION))
    op.execute(STAND_DOWN.format(name=NAME))
    op.execute(RAISE_NEWEST.format(name=NAME))


def downgrade() -> None:
    op.execute(
        f"DELETE FROM ai_prompt_templates WHERE name = '{NAME}' "
        f"AND version = (SELECT max(version) FROM ai_prompt_templates "
        f"WHERE name = '{NAME}')"
    )
    op.execute(STAND_DOWN.format(name=NAME))
    op.execute(RAISE_NEWEST.format(name=NAME))
