"""Teach generated calculation steps the complete renderer contract.

Revision ID: 20261013_0099
Revises: 20261012_0097
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261013_0099"
down_revision: str | Sequence[str] | None = "20261012_0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "content_parse.default"

ADDITION = """
 For every calculation step also return requiredCharacters (the exact
 non-digit keys its typed answer needs), resultTargetId, equationTokens and
 highlights. Every equation token, scaffold mark and draggable piece has a
 stable id. The result token is hiddenUntilAccepted and is named by a result
 highlight, so an answer is never visible before the learner builds it.
 A number_line scaffold always carries start. Manipulative kind must be one
 of fraction_bar, number_line, array, place_value or counters; the equivalent
 scaffold drawing kinds are bar, number_line, array, place_value and dots.
"""


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO ai_prompt_templates (
            service, name, version, system_template, user_template,
            required_variables, active
        )
        SELECT service, name, version + 1, system_template || $tpl${ADDITION}$tpl$,
               user_template, required_variables, false
        FROM ai_prompt_templates
        WHERE name = '{NAME}'
          AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = '{NAME}')
        """
    )
    op.execute(f"UPDATE ai_prompt_templates SET active = false WHERE name = '{NAME}'")
    op.execute(
        f"""
        UPDATE ai_prompt_templates SET active = true
        WHERE name = '{NAME}'
          AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = '{NAME}')
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM ai_prompt_templates
        WHERE name = '{NAME}'
          AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = '{NAME}')
        """
    )
    op.execute(
        f"""
        UPDATE ai_prompt_templates SET active = true
        WHERE name = '{NAME}'
          AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = '{NAME}')
        """
    )
