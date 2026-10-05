"""Renderer-ready calculations and lower-depth reroute sessions.

Revision ID: 20260927_0080
Revises: 20260924_0079
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260927_0080"
down_revision: str | Sequence[str] | None = "20260924_0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "content_parse.default"
ADDITION = (
    " For each calculation emit expression and an optional scaffold object. "
    "Scaffold kind is exactly one of bar, number_line, dots, array or place_value, "
    "with parts, rows, marks and labels. Each step emits input, exactly one of tap, "
    "choice or number; targets; and assembles, the equation text after that step. "
    "Support fractions across all four operations with like and unlike denominators, "
    "then whole numbers and decimals with place value, then ratio. If no supported "
    "scaffold honestly represents the calculation, omit scaffold. Never emit "
    "scaffoldImage or request a generated image for a calculation."
)


def upgrade() -> None:
    op.add_column(
        "lesson_sessions",
        sa.Column(
            "delivery_depth", sa.String(length=16), nullable=False, server_default="standard"
        ),
    )
    op.add_column(
        "lesson_sessions",
        sa.Column("rerouted_from_session_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_lesson_sessions_rerouted_from_session_id_lesson_sessions",
        "lesson_sessions",
        "lesson_sessions",
        ["rerouted_from_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        sa.text(
            """
            INSERT INTO ai_prompt_templates (
                service, name, version, system_template, user_template,
                required_variables, active
            )
            SELECT service, name, version + 1, system_template || :addition,
                   user_template, required_variables, false
            FROM ai_prompt_templates
            WHERE name = :name
              AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = :name)
            """
        ).bindparams(addition=ADDITION, name=NAME)
    )
    op.execute(
        sa.text("UPDATE ai_prompt_templates SET active = false WHERE name = :name").bindparams(
            name=NAME
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE ai_prompt_templates SET active = true
            WHERE name = :name
              AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = :name)
            """
        ).bindparams(name=NAME)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM ai_prompt_templates
            WHERE name = :name
              AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = :name)
            """
        ).bindparams(name=NAME)
    )
    op.execute(
        sa.text(
            """
            UPDATE ai_prompt_templates SET active = true
            WHERE name = :name
              AND version = (SELECT max(version) FROM ai_prompt_templates WHERE name = :name)
            """
        ).bindparams(name=NAME)
    )
    op.drop_constraint(
        "fk_lesson_sessions_rerouted_from_session_id_lesson_sessions",
        "lesson_sessions",
        type_="foreignkey",
    )
    op.drop_column("lesson_sessions", "rerouted_from_session_id")
    op.drop_column("lesson_sessions", "delivery_depth")
