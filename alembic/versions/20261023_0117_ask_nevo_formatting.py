"""Give Ask Nevo responses a consistent readable layout.

Revision ID: 20261023_0117
Revises: 20261023_0116
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261023_0117"
down_revision: str | Sequence[str] | None = "20261023_0116"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FORMAT_RULES = (
    " Format every response for easy reading. Start with one short, useful title "
    "on its own line, wrapped in **bold** markers, then leave a blank line. "
    "Use short paragraphs separated by blank lines. Use bullets for separate "
    "points and numbered steps only when order matters. Keep headings concise; "
    "do not put a heading on every paragraph. Never emit stray or unmatched "
    "asterisks, repeated blank lines, or decorative separators."
)


def upgrade() -> None:
    for name in ("ask_nevo.student", "ask_nevo.teacher", "ask_nevo.parent"):
        op.execute(
            sa.text(
                """
                INSERT INTO ai_prompt_templates (
                    service, name, version, system_template, user_template,
                    required_variables, active
                )
                SELECT service, name, version + 1,
                       system_template || :rules, user_template,
                       required_variables, false
                FROM ai_prompt_templates
                WHERE name = :name
                  AND version = (
                      SELECT max(version) FROM ai_prompt_templates WHERE name = :name
                  )
                """
            ).bindparams(name=name, rules=FORMAT_RULES)
        )
        op.execute(
            sa.text("UPDATE ai_prompt_templates SET active = false WHERE name = :name")
            .bindparams(name=name)
        )
        op.execute(
            sa.text(
                """
                UPDATE ai_prompt_templates SET active = true
                WHERE name = :name
                  AND version = (
                      SELECT max(version) FROM ai_prompt_templates WHERE name = :name
                  )
                """
            ).bindparams(name=name)
        )


def downgrade() -> None:
    for name in ("ask_nevo.student", "ask_nevo.teacher", "ask_nevo.parent"):
        op.execute(
            sa.text(
                """
                DELETE FROM ai_prompt_templates
                WHERE name = :name
                  AND version = (
                      SELECT max(version) FROM ai_prompt_templates WHERE name = :name
                  )
                """
            )
            .bindparams(name=name)
        )
        op.execute(
            sa.text(
                """
                UPDATE ai_prompt_templates SET active = true
                WHERE name = :name
                  AND version = (
                      SELECT max(version) FROM ai_prompt_templates WHERE name = :name
                  )
                """
            ).bindparams(name=name)
        )

