"""Ask for what a co-construction step needs on screen.

A step said which gesture it wanted - selection, numeric, text or drag - and
nothing about what to render for any of them. No options for a selection, no
expected value for a numeric, no targets for a drag. The variant's answer is
the whole problem's total, and mapping it onto the last step is wrong at the
units: a step inside a fraction scaffold wants a numerator, not a total.

Revision ID: 20260915_0057
Revises: 20260915_0056
Create Date: 2026-09-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260915_0057"
down_revision: str | Sequence[str] | None = "20260915_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADDITION = (
    " Every calculation step also carries answer: what that one step is "
    "answered with, in the units that step asks for, which is not the whole "
    "problem's total. Give it as a number when the step wants a number. A "
    "step whose expectedInput is selection or drag must carry options too: at "
    "least two entries of value and label, one of them matching the step's "
    "answer, because a step offering nothing to choose between cannot be "
    "answered. Add unit - naira, years, % - where saying so makes the step "
    "answerable and the prompt does not already carry it."
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
