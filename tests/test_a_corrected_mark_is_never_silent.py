"""A teacher can correct a mark; the correction is recorded, never silent.

T12 / SCRUM-350. An answer can be right in a way a comparison cannot see - a
child writes "half" where the key says 0.5 - so a teacher has to be able to
change how it was marked.

It is also the one write in the system where an adult changes the record of
what a child did. So the mark is corrected on the attempt, because mastery
and every report read `correct` and must be right without knowing overrides
exist, and the decision is appended beside it with the machine's own mark,
the teacher, the time, and a reason.
"""

from __future__ import annotations

import inspect

from nevo.api import insights
from nevo.api.insights import MarkOverrideWrite
from nevo.db.models.mark_override import LessonMarkOverride


def test_a_reason_is_required_and_not_a_formality() -> None:
    """A mark changed with no reason is indistinguishable from a mistake."""
    field = MarkOverrideWrite.model_fields["reason"]
    assert field.is_required()
    constraints = str(field.metadata)
    assert "min_length=3" in constraints


def test_the_machines_own_mark_is_kept() -> None:
    columns = LessonMarkOverride.__table__.c
    assert "previous_correct" in columns
    # Nullable: an answer that was never marked at all is a different
    # situation from one marked wrong.
    assert columns.previous_correct.nullable
    assert columns.corrected_to.nullable is False


def test_the_teacher_cannot_be_deleted_out_from_under_the_record() -> None:
    """An override with no attributable teacher is not an audit record."""
    teacher = LessonMarkOverride.__table__.c.teacher_id
    assert all(fk.ondelete == "RESTRICT" for fk in teacher.foreign_keys)


def test_a_childs_data_purge_still_reaches_these_rows() -> None:
    """The student link cascades, so a purge does not leave orphans behind."""
    student = LessonMarkOverride.__table__.c.student_id
    assert all(fk.ondelete == "CASCADE" for fk in student.foreign_keys)


def test_the_database_refuses_a_blank_reason_and_a_no_op() -> None:
    # The project's naming convention prefixes these, and a name over 63
    # characters gets truncated with a hash - so the suffix is what is
    # stable, and the names were shortened until nothing was truncated.
    names = {
        constraint.name
        for constraint in LessonMarkOverride.__table__.constraints
        if constraint.name
    }
    assert any(name.endswith("mark_has_a_reason") for name in names)
    assert any(name.endswith("mark_changes_the_mark") for name in names)


def test_only_school_staff_can_change_a_mark() -> None:
    """A child correcting their own mark is the end of the mastery estimate
    meaning anything, and a parent is not the marker either."""
    source = inspect.getsource(insights.correct_a_mark)
    assert "UserRole.TEACHER" in source
    assert "UserRole.SENCO_ADMIN" in source
    assert "UserRole.OTHER_ADMIN" in source
    assert '"teacher_required"' in source
    # Access to the child is checked before the role, so a teacher at another
    # school cannot probe for attempts either.
    assert source.index("require_student_access") < source.index("UserRole.TEACHER")


def test_another_childs_attempt_reads_as_absent_not_forbidden() -> None:
    """A 403 would confirm the attempt exists."""
    source = inspect.getsource(insights.correct_a_mark)
    assert "attempt.student_id != student_id" in source
    assert '"attempt_not_found"' in source


def test_the_attempt_itself_carries_the_corrected_mark() -> None:
    """Everything downstream reads `correct`; it must not have to know about
    overrides to be right."""
    source = inspect.getsource(insights.correct_a_mark)
    assert "attempt.correct = payload.correct" in source
    # And the previous value is captured before it is overwritten.
    assert source.index("previous = attempt.correct") < source.index(
        "attempt.correct = payload.correct"
    )


def test_an_override_that_changes_nothing_is_refused() -> None:
    source = inspect.getsource(insights.correct_a_mark)
    assert "attempt.correct is payload.correct" in source
    assert '"mark_unchanged"' in source
