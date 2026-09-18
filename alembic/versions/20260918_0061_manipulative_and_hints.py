"""Ask the parser for what a drag step needs, and for hint text.

A calculation step could declare expectedInput "drag" and carry nothing to
drag, so drag was refused on generated content and the one place modalities
layer rather than switch never happened.

Revision ID: 20260918_0061
Revises: 20260918_0060
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260918_0061"
down_revision: str | Sequence[str] | None = "20260918_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADDITION = (
    " When a calculation is better worked by moving pieces than by typing, "
    "give the variant a manipulative: kind, one of fraction_bar, number_line, "
    "array, place_value or counters; parts, how many equal pieces the whole "
    "divides into; rows, how those pieces are laid out, 1 for a bar or a "
    "line. Any step whose expectedInput is drag requires it - a step that "
    "asks a learner to drag with nothing to drag cannot be shown, and the "
    "variant is refused."
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
