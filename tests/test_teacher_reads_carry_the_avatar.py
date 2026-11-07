"""A teacher's list of children shows the avatar, not just initials.

Lydia, 7 November: children's avatars now show on teacher screens instead
of initials, and initials collide - in a class of forty they will collide
more than once, so a name is not enough to pick a child out of a list.

Shape and colourway are deliberately not here. They exist only against a
shared device, in shared_device_profiles, and not against the child, so
putting them on a teacher's read of a student needs columns that do not
exist yet and a decision about whose shape names win.
"""

from __future__ import annotations

from nevo.api.frontend_unblockers import ClassStudentResponse
from nevo.api.response_models import StudentSummaryResponse
from nevo.main import app

SPEC = app.openapi()


def test_both_teacher_facing_reads_carry_it() -> None:
    for name in ("ClassStudentResponse", "StudentSummaryResponse"):
        properties = SPEC["components"]["schemas"][name]["properties"]
        assert "avatarTone" in properties, name
        assert "profileImageUrl" in properties, name


def test_a_child_with_no_avatar_is_null_not_absent() -> None:
    # The screen falls back to initials for that one child rather than
    # having to handle a missing key.
    assert ClassStudentResponse.model_fields["avatar_tone"].default is None
    assert StudentSummaryResponse.model_fields["profile_image_url"].default is None


def test_the_image_is_read_from_where_the_patch_writes_it() -> None:
    # profileImageUrl is kept in user.preferences, not a column. Reading
    # user.profile_image_url raises, because there is no such attribute.
    import inspect

    from nevo.api import frontend_unblockers

    source = inspect.getsource(frontend_unblockers.class_students)
    assert '(user.preferences or {}).get("profileImageUrl")' in source
