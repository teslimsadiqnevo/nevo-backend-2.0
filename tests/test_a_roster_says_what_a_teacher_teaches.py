"""A teacher roster says which classes, not only how many.

T14's first half. classCount said "3" against a name and never which three,
so an admin had to open each teacher in turn to find out who covers JSS 2B.

The second half of T14 - a parent or guardian on a student summary - is
deliberately not here. The link exists through consent records, so it is
buildable, but putting a guardian's name on a student list is a disclosure
decision rather than a formatting one, and that decision is Lydia's. Shipping
it first and asking afterwards would be the wrong order for exactly the kind
of data this team keeps a register for.
"""

from __future__ import annotations

import inspect

from nevo.api import product_admin
from nevo.api.response_models import StudentSummaryResponse, TeacherSummaryResponse


def test_a_teacher_says_which_classes_they_hold() -> None:
    assert "teaches" in TeacherSummaryResponse.model_fields
    assert TeacherSummaryResponse.model_fields["teaches"].default_factory is list


def test_it_is_one_grouped_query_for_the_page() -> None:
    """Not one per teacher. At ~280ms a round trip that is the difference
    between a roster that loads and one that does not."""
    source = inspect.getsource(product_admin._class_names_by_teacher)
    assert "teacher_id.in_(teacher_ids)" in source
    assert "if not teacher_ids:" in source
    listing = inspect.getsource(product_admin.list_teachers)
    assert listing.count("_class_names_by_teacher(") == 1


def test_a_teacher_removed_from_a_class_is_not_shown_teaching_it() -> None:
    """The same filter the count uses, so the two agree by construction."""
    source = inspect.getsource(product_admin._class_names_by_teacher)
    assert "removed_at.is_(None)" in source
    listing = inspect.getsource(product_admin.list_teachers)
    assert "removed_at.is_(None)" in listing


def test_an_archived_class_is_not_shown_as_taught() -> None:
    source = inspect.getsource(product_admin._class_names_by_teacher)
    assert "archived_at.is_(None)" in source


def test_a_guardian_name_has_not_been_added_to_a_student_summary() -> None:
    """Holds the line until Lydia has made the disclosure decision.

    If this test starts failing, either the decision was made and this test
    should be updated to match it, or a guardian's name reached a roster
    without anyone deciding it should.
    """
    fields = set(StudentSummaryResponse.model_fields)
    assert not {"parent", "guardian", "parent_name", "guardian_name"} & fields
