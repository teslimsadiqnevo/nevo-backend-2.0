"""A teacher is told a lesson was completed only when it was.

Home's activity was built from every ended sitting. A sitting ends whenever a
child stops, and "Leave for now" ends one, so leaving a lesson partway was
announced as completing it. Tunde left Speed partway twice and his teacher was
told twice that he had completed it.

The scale of it, in production when this was found: 88 ended sittings against
14 completed lessons.

lesson_progress carries completed_at and is unique on (student, lesson), so
reading from it gives both halves of what Yinka asked for - actually
completed, and once per lesson - with nothing to de-duplicate here.
"""

from __future__ import annotations

from nevo.api import insights
from nevo.db.models.product import LessonProgress


def _activity_source() -> str:
    source = insights.__loader__.get_source(insights.__name__)
    start = source.index("async def _teacher_recent_activity")
    return source[start : source.index("for flag, student in flag_rows", start)]


def test_completions_are_not_read_from_ended_sittings() -> None:
    body = _activity_source()
    assert "LessonSession.ended_at.is_not(None)" not in body, (
        "an ended sitting is a child stopping, not a child finishing"
    )


def test_completions_come_from_the_completion_record() -> None:
    body = _activity_source()
    assert "LessonProgress.completed_at.is_not(None)" in body
    assert "LessonProgress.completed_at.desc()" in body


def test_the_claim_is_dated_by_when_the_lesson_was_completed() -> None:
    body = _activity_source()
    assert '"occurredAt": progress.completed_at' in body
    assert "lesson_session.ended_at" not in body


def test_one_entry_per_lesson_rather_than_per_sitting() -> None:
    """Two sittings on one lesson must not read as two completions."""
    body = _activity_source()
    assert 'f"session:{lesson_session.id}"' not in body
    assert "lesson-completed:" in body


def test_the_record_it_reads_is_unique_per_child_and_lesson() -> None:
    """Which is why no de-duplicating is needed in the query.

    If this constraint ever goes, the once-per-lesson guarantee goes with it
    and this test is the thing that should fail.
    """
    names = {
        constraint.name for constraint in LessonProgress.__table__.constraints if constraint.name
    }
    assert "uq_lesson_progress_student_lesson" in names
    unique = next(
        constraint
        for constraint in LessonProgress.__table__.constraints
        if constraint.name == "uq_lesson_progress_student_lesson"
    )
    assert {column.name for column in unique.columns} == {"student_id", "lesson_id"}


def test_a_completion_record_without_a_date_is_not_counted() -> None:
    """status alone is not the test; the date is.

    In production all 14 completed rows carry completed_at, and the
    in_progress and exited rows carry none, so the date is the honest filter.
    """
    body = _activity_source()
    assert 'LessonProgress.status == "completed"' not in body
    assert "LessonProgress.completed_at.is_not(None)" in body
