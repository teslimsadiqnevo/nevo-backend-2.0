"""An upload may belong to no school.

/me, Phase 3. A /me learner uploads their own material for an audience of
one. The upload job is theirs (requested_by_id) and belongs to no school,
exactly as the lesson it becomes does (lessons.school_id is already
nullable). Every school upload keeps its school; nothing is backfilled.

0152, 24 November 2026.
"""

from alembic import op

revision = "20261124_0152"
down_revision = "20261124_0151"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("upload_jobs", "school_id", nullable=True)


def downgrade() -> None:
    # Refuses if any individual upload exists, which is the right answer:
    # deleting a learner's uploads to make a downgrade fit is not this
    # migration's decision to make.
    op.alter_column("upload_jobs", "school_id", nullable=False)
