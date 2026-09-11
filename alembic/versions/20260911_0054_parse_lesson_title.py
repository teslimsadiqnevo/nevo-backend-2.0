"""Ask the parser to name the lesson.

The title came from the uploaded filename and nothing else, so a teacher's
library filled up with `simple interest jss3` - the file, not the lesson. The
parser reads the whole document and is the one thing in the pipeline that
knows what it is about.

Revision ID: 20260911_0054
Revises: 20260911_0053
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260911_0054"
down_revision: str | Sequence[str] | None = "20260911_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADDITION = (
    " Also return title: what this lesson is called, drawn from the source's "
    "own heading where it has one. Name the lesson, not the file it arrived "
    "in, and keep it short enough to read in a list - a few words, no "
    "trailing punctuation, no year group unless the source itself carries "
    "one."
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
