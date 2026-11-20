"""An invitation carries several classes, each with a subject.

A teacher invitation used to carry a single class_id and nothing else, so a
subject teacher covering six classes had to be invited six times on the first
day of setup - the same person, six emails, six passwords to set. Lydia
approved several classes per invitation on 20 November.

A row per class *and* subject, because one teacher can take two subjects to
the same class and the pair is what an assignment is keyed on. The subject is
NOT NULL: SCRUM-194 means a teacher cannot be assigned without one, so an
invitation naming a class and no subject could never be applied, and refusing
it when it is written is better than discovering it at acceptance.

T15, 20 November.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261120_0147"
down_revision = "20261120_0146"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "school_invitation_classes",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("school_subject_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"], ["school_invitations.id"], ondelete="CASCADE"
        ),
        # A class deleted before the invitation is accepted takes this row
        # with it, which is correct: there is nothing left to attach to, and
        # acceptance attaches the classes that remain.
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["school_subject_id"], ["school_subjects.id"], ondelete="CASCADE"
        ),
        # Inviting somebody twice to the same class and subject is a
        # duplicate, not two assignments.
        sa.UniqueConstraint(
            "invitation_id",
            "class_id",
            "school_subject_id",
            name="uq_invitation_class_subject",
        ),
    )
    op.create_index(
        "ix_school_invitation_classes_invitation",
        "school_invitation_classes",
        ["invitation_id"],
    )
    op.create_index(
        "ix_school_invitation_classes_class",
        "school_invitation_classes",
        ["class_id"],
    )

    # The existing single class_id is left exactly as it is, on both the
    # invitations already sent and the column itself. Backfilling it into this
    # table would mean inventing a subject for each one, which is the thing
    # SCRUM-194 forbids - and those invitations were written under the old
    # behaviour, where a teacher's class was recorded and never applied.
    # Changing what they do on acceptance after the fact would be a surprise.


def downgrade() -> None:
    op.drop_index(
        "ix_school_invitation_classes_class", table_name="school_invitation_classes"
    )
    op.drop_index(
        "ix_school_invitation_classes_invitation",
        table_name="school_invitation_classes",
    )
    op.drop_table("school_invitation_classes")
