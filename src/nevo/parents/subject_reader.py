"""Reading one child's week out of the mastery and session tables."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.db.models.account import Class, School, StudentClassEnrollment
from nevo.db.models.content import Lesson
from nevo.db.models.frontend_support import Concept
from nevo.db.models.mastery import StudentConceptMastery
from nevo.db.models.signal_event import LessonSession
from nevo.db.models.subject import CanonicalSubject, ClassSubject, SchoolSubject
from nevo.parents.subject_progress import (
    MASTERED_AT,
    ChildSubjectProgress,
    SubjectProgress,
    SubjectState,
    build_window,
    window_bounds,
)

#: Where a school's half-term breaks live, when it has set any. Absent for every
#: school until D12b writes them, which is why the reader treats an empty list
#: as "no break configured" rather than as an error.
BREAKS_KEY = "half_term_breaks"
TERM_DATES_KEY = "term_start_dates"


def _dates(raw: object) -> list[date]:
    if not isinstance(raw, list):
        return []
    parsed: list[date] = []
    for item in raw:
        try:
            parsed.append(date.fromisoformat(str(item)))
        except ValueError:
            # One unreadable date does not make the others unusable, but it
            # does mean we cannot trust the set to bound a term, so drop all.
            return []
    return sorted(parsed)


def _breaks(raw: object) -> list[tuple[date, date]]:
    if not isinstance(raw, list):
        return []
    spans: list[tuple[date, date]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            start = date.fromisoformat(str(item.get("start")))
            end = date.fromisoformat(str(item.get("end")))
        except ValueError:
            continue
        if end >= start:
            spans.append((start, end))
    return spans


async def child_subject_progress(
    session: AsyncSession,
    *,
    student_id: UUID,
    now: datetime,
    week_of: date | None = None,
) -> ChildSubjectProgress:
    """One child's week, by subject.

    A subject the class holds with no lesson yet comes back marked not_started
    rather than being left out: the front end has a state for it, and an
    omission is indistinguishable from a bug.
    """

    school_id = await session.scalar(
        select(Class.school_id)
        .join(StudentClassEnrollment, StudentClassEnrollment.class_id == Class.id)
        .where(StudentClassEnrollment.student_id == student_id)
        .limit(1)
    )
    academic = {}
    if school_id is not None:
        school = await session.get(School, school_id)
        academic = school.academic_config if school else {}
    window = build_window(
        now=now,
        starts_on=week_of,
        term_starts=_dates(academic.get(TERM_DATES_KEY)),
        breaks=_breaks(academic.get(BREAKS_KEY)),
    )
    opened_at, closed_at = window_bounds(window.starts_on, window.ends_on)

    subjects = (
        await session.execute(
            select(SchoolSubject.id, SchoolSubject.name, CanonicalSubject.display_name)
            .join(ClassSubject, ClassSubject.school_subject_id == SchoolSubject.id)
            .join(StudentClassEnrollment, StudentClassEnrollment.class_id == ClassSubject.class_id)
            .outerjoin(CanonicalSubject, CanonicalSubject.id == SchoolSubject.canonical_subject_id)
            .where(StudentClassEnrollment.student_id == student_id)
            .distinct()
        )
    ).all()

    # Concepts this child touched in the window, by subject name on the concept.
    touched = (
        await session.execute(
            select(Concept.subject, Concept.name)
            .join(Lesson, Lesson.id == Concept.lesson_id)
            .join(LessonSession, LessonSession.lesson_id == Lesson.id)
            .where(
                LessonSession.student_id == student_id,
                LessonSession.started_at >= opened_at,
                LessonSession.started_at < closed_at,
            )
            .distinct()
        )
    ).all()
    covered_by_subject: dict[str, list[str]] = {}
    for subject_name, concept_name in touched:
        covered_by_subject.setdefault((subject_name or "").casefold(), []).append(concept_name)

    mastery = (
        await session.execute(
            select(
                Concept.subject,
                Concept.name,
                StudentConceptMastery.mastery_probability_concept,
                StudentConceptMastery.last_updated,
                StudentConceptMastery.practice_count,
            )
            .join(Concept, Concept.id == StudentConceptMastery.concept_id)
            .where(StudentConceptMastery.student_id == student_id)
        )
    ).all()

    rows: list[SubjectProgress] = []
    for subject_id, own_name, canonical_name in subjects:
        name = canonical_name or own_name
        key = name.casefold()
        covered = sorted(set(covered_by_subject.get(key, ())))
        mastered_now: list[str] = []
        working: list[str] = []
        mastered_before = 0
        for subject_name, concept_name, probability, last_updated, practices in mastery:
            if (subject_name or "").casefold() != key:
                continue
            if probability >= MASTERED_AT:
                if last_updated is not None and opened_at <= last_updated < closed_at:
                    mastered_now.append(concept_name)
                else:
                    # Already there when the window opened. Counted, not named:
                    # a parent wants this week's movement, with last week's as
                    # the ground it stands on.
                    mastered_before += 1
            elif practices:
                working.append(concept_name)
        state = (
            SubjectState.ACTIVE
            if covered or mastered_now or working or mastered_before
            else SubjectState.NOT_STARTED
        )
        rows.append(
            SubjectProgress(
                subject_id=subject_id,
                subject_name=name,
                state=state,
                covered=tuple(covered),
                mastered_this_window=tuple(sorted(set(mastered_now))),
                still_working_on=tuple(sorted(set(working))),
                mastered_before_window=mastered_before,
            )
        )
    rows.sort(key=lambda row: row.subject_name)
    return ChildSubjectProgress(student_id=student_id, window=window, subjects=tuple(rows))
