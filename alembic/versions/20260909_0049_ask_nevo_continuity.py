"""Tell Ask Nevo that a chat has a before.

Revision ID: 20260909_0049
Revises: 20260909_0048
Create Date: 2026-09-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260909_0049"
down_revision: str | Sequence[str] | None = "20260909_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTINUITY = (
    " The context may include conversation_so_far: what has already been said "
    "in this chat, oldest first, where \"them\" is the person you are talking "
    "to and \"you\" is your own earlier reply. Read a short follow-up as "
    "continuing that conversation rather than as a new question - \"explain "
    "that again\" means the thing you just said. Do not repeat an earlier "
    "answer back at them; answer what they have just asked."
)

# One new version per prompt, carrying the previous system text plus the
# continuity paragraph. Copied from whatever is latest rather than restated,
# so this does not quietly undo an earlier wording change.
#
# Only one version of a prompt may be active at a time, so the new row is
# inserted inactive, every version is stood down, and the newest is raised.
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

PROMPTS = ("ask_nevo.student", "ask_nevo.teacher", "ask_nevo.parent")


def upgrade() -> None:
    for name in PROMPTS:
        op.execute(INSERT_INACTIVE.format(name=name, addition=CONTINUITY))
        op.execute(STAND_DOWN.format(name=name))
        op.execute(RAISE_NEWEST.format(name=name))


def downgrade() -> None:
    for name in PROMPTS:
        op.execute(
            f"DELETE FROM ai_prompt_templates WHERE name = '{name}' "
            f"AND version = (SELECT max(version) FROM ai_prompt_templates "
            f"WHERE name = '{name}')"
        )
        op.execute(STAND_DOWN.format(name=name))
        op.execute(RAISE_NEWEST.format(name=name))
