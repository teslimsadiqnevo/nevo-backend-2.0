"""The avatar belongs to the child, not to the tablet.

SCRUM-314, Lydia's ruling of 7 November. The shape and colour scheme were
stored against a shared device, so a child's own identity in the product
changed when they picked up a different tablet, and a teacher's view of a
child could not show something that existed only on a piece of hardware.

They move onto the child. The collision rule stays where it is useful,
which is at selection: when a child is first given an avatar, combinations
already taken by other children on that device are excluded. That is a
selection constraint rather than a storage decision, so the unique
constraint that enforced it per device goes - a child who already owns an
avatar keeps it when they move to a tablet where somebody else owns the
same one, because identity must not change per device.

Existing shapes and colourways are copied up from the device rows rather
than reassigned, so no child's avatar changes on deploy. Where a child has
tiles on two devices the earliest provisioning wins, which is the one they
have had longest.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261107_0138"
down_revision = "20261106_0137"
branch_labels = depends_on = None


def upgrade():
    op.add_column("users", sa.Column("avatar_shape", sa.String(24), nullable=True))
    op.add_column("users", sa.Column("avatar_colourway", sa.String(24), nullable=True))
    # Copied up, not reassigned: a child's avatar must not change on deploy.
    op.execute(
        """
        UPDATE users SET
            avatar_shape = earliest.avatar_shape,
            avatar_colourway = earliest.avatar_colourway
        FROM (
            SELECT DISTINCT ON (student_id)
                student_id, avatar_shape, avatar_colourway
            FROM shared_device_profiles
            ORDER BY student_id, created_at, id
        ) AS earliest
        WHERE users.id = earliest.student_id
        """
    )
    # The collision rule moves to selection time. Kept as a constraint it
    # would refuse to provision a child who already owns an avatar onto a
    # tablet where another child owns the same one, which is the identity
    # changing per device that this ruling removes.
    op.drop_constraint(
        "uq_shared_device_profiles_device_avatar",
        "shared_device_profiles",
        type_="unique",
    )


def downgrade():
    op.create_unique_constraint(
        "uq_shared_device_profiles_device_avatar",
        "shared_device_profiles",
        ["device_id", "avatar_shape", "avatar_colourway"],
    )
    op.drop_column("users", "avatar_colourway")
    op.drop_column("users", "avatar_shape")
