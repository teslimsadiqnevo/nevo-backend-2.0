"""Class merge decisions, and the subject spelling question. SCRUM-204.

Two things OB-02 needs a place to remember.

A proposed class merge has to be answerable, and "no, we really do run JSS 2A
and JSS2A separately" has to stick - otherwise the school is asked the same
question on every read and can never confirm its headcount.

And where a teacher file carried Maths on one row and Mathematics on another,
the two are folded into one subject at import, because two subjects split a
child's mastery across two knowledge graphs. The fold would lose the words the
school actually typed, so they are kept here and the question is put on the
classes screen afterwards.

Revision ID: 20260930_0087
Revises: 20260930_0086
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260930_0087"
down_revision = "20260930_0086"
branch_labels = None
depends_on = None

SPELLING_ANSWER = "subject_spelling_answer"


def upgrade() -> None:
    op.add_column(
        "school_onboardings",
        sa.Column(
            "class_merge_decisions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    answer = postgresql.ENUM(
        "unanswered",
        "same",
        "different",
        name=SPELLING_ANSWER,
        create_type=False,
    )
    answer.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "subject_spelling_questions",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("kept_subject_id", sa.Uuid(), nullable=False),
        sa.Column("other_label", sa.String(length=120), nullable=False),
        sa.Column("normalised_other", sa.String(length=120), nullable=False),
        sa.Column(
            "answer",
            answer,
            nullable=False,
            server_default="unanswered",
        ),
        sa.Column("split_subject_id", sa.Uuid(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kept_subject_id"], ["school_subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["split_subject_id"], ["school_subjects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "school_id",
            "kept_subject_id",
            "normalised_other",
            name="uq_subject_spelling_questions",
        ),
    )
    op.create_index(
        "ix_subject_spelling_questions_school",
        "subject_spelling_questions",
        ["school_id", "answer"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subject_spelling_questions_school",
        table_name="subject_spelling_questions",
    )
    op.drop_table("subject_spelling_questions")
    postgresql.ENUM(name=SPELLING_ANSWER).drop(op.get_bind(), checkfirst=True)
    op.drop_column("school_onboardings", "class_merge_decisions")
