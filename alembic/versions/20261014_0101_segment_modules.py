"""Store optional module membership for lesson segments."""

import sqlalchemy as sa

from alembic import op

revision = "20261014_0101"
down_revision = "20261014_0100"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("lesson_segments", sa.Column("module_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_lesson_segments_module",
        "lesson_segments",
        "lesson_modules",
        ["module_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_lesson_segments_module_id", "lesson_segments", ["module_id"])
    op.execute("""UPDATE lesson_segments AS segment SET module_id = module.id
        FROM lesson_modules AS module
        WHERE segment.lesson_id = module.lesson_id
        AND (module.segment_ids @> jsonb_build_array(segment.segment_key)
             OR module.segment_ids @> jsonb_build_array(segment.id::text))""")


def downgrade():
    op.drop_index("ix_lesson_segments_module_id", table_name="lesson_segments")
    op.drop_constraint("fk_lesson_segments_module", "lesson_segments", type_="foreignkey")
    op.drop_column("lesson_segments", "module_id")
