"""Version mastery updates without rewriting historical estimates."""

import sqlalchemy as sa

from alembic import op

revision = "20261019_0108"
down_revision = "20261019_0107"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "student_concept_mastery",
        sa.Column("model_version", sa.String(40), nullable=False, server_default="legacy_v1"),
    )
    op.add_column(
        "student_concept_mastery",
        sa.Column("transition_probability", sa.Float(), nullable=False, server_default="0.16"),
    )
    op.create_check_constraint(
        "mastery_transition_range",
        "student_concept_mastery",
        "transition_probability BETWEEN 0 AND 1",
    )


def downgrade():
    op.drop_constraint(
        op.f("ck_student_concept_mastery_mastery_transition_range"),
        "student_concept_mastery",
        type_="check",
    )
    op.drop_column("student_concept_mastery", "transition_probability")
    op.drop_column("student_concept_mastery", "model_version")
