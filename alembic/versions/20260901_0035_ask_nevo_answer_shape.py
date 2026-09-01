"""Let Ask Nevo choose the shape its answer needs.

Revision ID: 20260901_0035
Revises: 20260901_0034
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260901_0035"
down_revision: str | Sequence[str] | None = "20260901_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The server normalises whatever comes back into blocks, so the model is asked
# to match the shape to the answer rather than to one fixed format. Without
# this the structure it produced was arbitrary - the same question could come
# back as prose one time and a bulleted list the next.
SHAPE = (
    " Match the shape to the answer: prose for a single point, a short "
    "bulleted list when you are naming several separate things, and numbered "
    "steps only when order matters. Do not add headings to a short answer, "
    "and never use tables, images or code blocks."
)

STUDENT = (
    "You are Ask Nevo for a student. Answer warmly, age-appropriately, "
    "and only from supplied lesson context. Never reveal raw learner "
    "profile data, confidence levels, or inference mechanics. Use "
    "functional learning language only." + SHAPE
)
TEACHER = (
    "You are Ask Nevo for a teacher. Respond like a thoughtful "
    "colleague leaving a useful note. Be specific to supplied class, "
    "student, lesson, flag, or thread data whenever IDs are present. "
    "Use functional learning language only." + SHAPE
)

# A partial unique index allows only one active row per name, so the previous
# version is stood down before the new one is inserted. These run as separate
# statements because asyncpg prepares each one and rejects multi-statement SQL.
DEACTIVATE = "UPDATE ai_prompt_templates SET active = false WHERE name = '{name}'"
INSERT_VERSION = """
    INSERT INTO ai_prompt_templates (
        service, name, version, system_template, user_template,
        required_variables, active
    )
    SELECT service, name, 2, $tpl${system}$tpl$, user_template,
           required_variables, true
    FROM ai_prompt_templates
    WHERE name = '{name}' AND version = 1
    ON CONFLICT (name, version) DO UPDATE
        SET system_template = EXCLUDED.system_template, active = true
"""


def upgrade() -> None:
    for name, system in (("ask_nevo.student", STUDENT), ("ask_nevo.teacher", TEACHER)):
        op.execute(DEACTIVATE.format(name=name))
        op.execute(INSERT_VERSION.format(name=name, system=system))


def downgrade() -> None:
    for name in ("ask_nevo.student", "ask_nevo.teacher"):
        op.execute(
            f"DELETE FROM ai_prompt_templates WHERE name = '{name}' AND version = 2"
        )
        op.execute(
            f"UPDATE ai_prompt_templates SET active = true "
            f"WHERE name = '{name}' AND version = 1"
        )
