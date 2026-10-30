"""Hold reviewed mastery evidence separately for each curriculum level."""

from alembic import op
import sqlalchemy as sa

revision = "20261030_0132"
down_revision = "20261030_0131"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "student_concept_level_mastery",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.Uuid(), nullable=False),
        sa.Column("mastery_level", sa.String(20), nullable=False),
        sa.Column("mastery_probability", sa.Float(), nullable=False, server_default="0.15"),
        sa.Column("practice_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("supported_pass_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("independent_pass_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_response_correct", sa.Boolean()),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("mastery_level IN ('knowledge', 'application', 'analysis')", name="level_mastery_level_valid"),
        sa.CheckConstraint("mastery_probability BETWEEN 0 AND 1", name="level_mastery_probability_range"),
        sa.CheckConstraint("practice_count >= 0 AND supported_pass_count >= 0 AND independent_pass_count >= 0", name="level_mastery_counts_nonnegative"),
        sa.UniqueConstraint("student_id", "concept_id", "mastery_level", name="uq_student_concept_level_mastery"),
    )
    op.create_index("ix_level_mastery_student", "student_concept_level_mastery", ["student_id"])


def downgrade():
    op.drop_index("ix_level_mastery_student", table_name="student_concept_level_mastery")
    op.drop_table("student_concept_level_mastery")
