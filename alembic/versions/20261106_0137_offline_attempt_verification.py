"""Record offline marking provenance and server verification for attempts."""

import sqlalchemy as sa

from alembic import op

revision = "20261106_0137"
down_revision = "20261106_0136"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "lesson_question_attempts",
        sa.Column("offline_marked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("lesson_question_attempts", sa.Column("marking_key_version", sa.String(64)))
    op.add_column(
        "lesson_question_attempts", sa.Column("server_verified_at", sa.DateTime(timezone=True))
    )
    op.execute("UPDATE lesson_question_attempts SET server_verified_at = submitted_at")


def downgrade():
    op.drop_column("lesson_question_attempts", "server_verified_at")
    op.drop_column("lesson_question_attempts", "marking_key_version")
    op.drop_column("lesson_question_attempts", "offline_marked")
