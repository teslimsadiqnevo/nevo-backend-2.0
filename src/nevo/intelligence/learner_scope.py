"""Which lessons and concepts belong to a learner, for either kind of account.

/me Phase 2. A school learner's work is what their school assigned them:
LessonAssignment rows on lessons of their school, concepts of their school.
An individual (/me) learner has no school and is never assigned anything;
their work is the lessons they uploaded themselves.

Every learner-surface lookup that used to say ``school_id ==
student.school_id`` asks here instead. For an individual that comparison is
against NULL, matches no rows and succeeds, which is the empty-page failure
the route guard exists to prevent - so it is never made.

An individual's lesson is one they created (``created_by_user_id``) that
belongs to no school. Phase 3's upload path is what creates them, and must
keep to that definition.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, or_, select
from sqlalchemy.sql.elements import ColumnElement

from nevo.db.models.account import User
from nevo.db.models.content import Lesson
from nevo.db.models.frontend_support import Concept, LessonAssignment

INDIVIDUAL = "individual"

#: OPEN PRODUCT QUESTION, default chosen 24 November 2026 so Phase 3 could be
#: built: does a lesson a /me learner uploads for themselves wait for a
#: teacher's review, as a school lesson does (Lydia, 7 November)? There is no
#: teacher in /me. Default: no - the learner is author and audience, and the
#: safety checker still runs and still holds what it holds. Lydia's to
#: confirm or reverse; reversing is setting this True.
INDIVIDUAL_LESSONS_NEED_TEACHER_REVIEW = False


def review_gate_applies(user: User) -> bool:
    return not is_individual(user) or INDIVIDUAL_LESSONS_NEED_TEACHER_REVIEW


def is_individual(user: User) -> bool:
    return getattr(user, "account_type", "school") == INDIVIDUAL


def owned_lessons(user: User) -> ColumnElement[bool]:
    """The filter for an individual's own lessons."""

    return (Lesson.created_by_user_id == user.id) & Lesson.school_id.is_(None)


def available_lesson_ids(user: User, now: datetime) -> Select:
    """Lessons this learner may work on now, completed by the parser."""

    if is_individual(user):
        return select(Lesson.id).where(owned_lessons(user), Lesson.status == "completed")
    return (
        select(LessonAssignment.lesson_id)
        .join(Lesson, Lesson.id == LessonAssignment.lesson_id)
        .where(
            LessonAssignment.student_id == user.id,
            LessonAssignment.status != "cancelled",
            or_(LessonAssignment.available_from.is_(None), LessonAssignment.available_from <= now),
            Lesson.school_id == user.school_id,
            Lesson.status == "completed",
        )
    )


def learner_concepts(user: User) -> ColumnElement[bool]:
    """The filter for concepts this learner's work can reach."""

    if is_individual(user):
        return Concept.lesson_id.in_(select(Lesson.id).where(owned_lessons(user)))
    return Concept.school_id == user.school_id
