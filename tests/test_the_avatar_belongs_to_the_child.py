"""A child's avatar does not change when they pick up a different tablet.

SCRUM-314, Lydia's ruling of 7 November. The shape and colour scheme were
stored against a shared device, so a child's own identity in the product
changed per tablet, and a teacher's view of a child could not show something
that existed only on a piece of hardware.

The collision rule stays where it is useful: when a child is first given an
avatar, combinations already held by the other children being provisioned
are excluded. That is a selection constraint, not a storage decision - so a
child who already owns an avatar keeps it on a tablet where somebody else
owns the same one, because identity must not change per device.
"""

from __future__ import annotations

import inspect

from nevo.api import product_auth
from nevo.db.models.account import User
from nevo.db.models.product import SharedDeviceProfile
from nevo.main import app

SPEC = app.openapi()


def test_the_child_holds_the_avatar() -> None:
    assert "avatar_shape" in User.__mapper__.columns
    assert "avatar_colourway" in User.__mapper__.columns


def test_the_device_no_longer_enforces_uniqueness() -> None:
    # Kept as a constraint it would refuse to provision a child who already
    # owns an avatar onto a tablet where another child owns the same one,
    # which is the identity changing per device that the ruling removes.
    names = {c.name for c in SharedDeviceProfile.__table__.constraints if c.name}
    assert "uq_shared_device_profiles_device_avatar" not in names
    # The one tile per child per device rule stays.
    assert "uq_shared_device_profiles_device_student" in names


def test_an_existing_avatar_is_kept_rather_than_reassigned() -> None:
    source = inspect.getsource(product_auth.provision_shared_device_profiles)
    assert "if not (student.avatar_shape and student.avatar_colourway):" in source


def test_collisions_are_avoided_only_when_choosing() -> None:
    source = inspect.getsource(product_auth.provision_shared_device_profiles)
    # Excludes what the other children already hold, rather than what this
    # device's rows happen to say.
    assert "student.avatar_shape and student.avatar_colourway" in source
    assert "unclaimed" in source


def test_the_tile_shows_the_childs_own_avatar() -> None:
    source = inspect.getsource(product_auth.provision_shared_device_profiles)
    assert '"shape": students[student_id].avatar_shape' in source


def test_the_teacher_can_see_it() -> None:
    # What unblocks SCRUM-317.
    for name in ("ClassStudentResponse", "StudentSummaryResponse"):
        properties = SPEC["components"]["schemas"][name]["properties"]
        assert "avatarShape" in properties, name
        assert "avatarColourway" in properties, name


def test_the_star_is_still_one_of_the_shapes() -> None:
    # The naming disagreement was settled the other way: the front end draws
    # the star rather than the server moving to a pill, so a migration that
    # moved every existing child's shape was avoided.
    assert "star" in product_auth.SHARED_DEVICE_SHAPES
    assert "pill" not in product_auth.SHARED_DEVICE_SHAPES
