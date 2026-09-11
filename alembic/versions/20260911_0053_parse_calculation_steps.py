"""Tell the parser what a co-construction step has to look like.

Calculation is the one modality that has never come out of a real parse. The
reason was not the model: the validator requires every step to carry an
``expectedInput`` of ``selection``, ``numeric``, ``text`` or ``drag``, and the
prompt never mentioned the field. Anything the model returned was rejected as
malformed, every time, and the segment lost its only interactive delivery.

Revision ID: 20260911_0053
Revises: 20260911_0052
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260911_0053"
down_revision: str | Sequence[str] | None = "20260911_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADDITION = (
    " A calculation variant needs steps: an array of at least two, one per "
    "line of working the learner should do themselves rather than read. Each "
    "step carries stepId, stepNumber, prompt asking the learner for that one "
    "line, expectedInput which must be exactly one of numeric, selection, "
    "text or drag, hint, confirmationText saying what the step established, "
    "and equationState showing the working so far. Use numeric when the "
    "learner types a figure, selection when they choose between given "
    "options. Also carry fullEquation for the whole calculation."
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
