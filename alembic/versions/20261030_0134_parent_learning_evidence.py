"""Record evidence threshold crossings and explicitly reported outside work."""

import sqlalchemy as sa
from alembic import op

revision = "20261030_0134"
down_revision = "20261030_0133"
branch_labels = depends_on = None


def upgrade():
    op.add_column("student_concept_level_mastery", sa.Column("strengthened_at", sa.DateTime(timezone=True)))
    op.create_table(
        "out_of_school_learning",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.Uuid(), sa.ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_kind", sa.String(24), nullable=False),
        sa.Column("client_event_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("client_event_id", name="uq_out_of_school_client_event"),
    )
    op.create_index("ix_out_of_school_learning_student_created", "out_of_school_learning", ["student_id", "created_at"])


def downgrade():
    op.drop_index("ix_out_of_school_learning_student_created", table_name="out_of_school_learning")
    op.drop_table("out_of_school_learning")
    op.drop_column("student_concept_level_mastery", "strengthened_at")
