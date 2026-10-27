from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select

from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.frontend_support import Concept, LessonAssignment
from nevo.db.models.product import LessonProgress
from nevo.db.models.mastery import StudentConceptMastery, StudentConceptScheduling
from nevo.intelligence.learning_runtime import MASTERY_THRESHOLD


async def next_work(session, student, subject=None, lesson_id=None):
    """Choose only assigned, available content with satisfied prerequisites."""
    now = datetime.now(UTC)
    assignment = (
        select(LessonAssignment.lesson_id)
        .join(Lesson, Lesson.id == LessonAssignment.lesson_id)
        .where(
            LessonAssignment.student_id == student.id,
            LessonAssignment.status != "cancelled",
            or_(LessonAssignment.available_from.is_(None), LessonAssignment.available_from <= now),
            Lesson.school_id == student.school_id,
            Lesson.status == "completed",
        )
    )
    from nevo.api.lesson_review import outstanding_key_points

    segments_query = select(LessonSegment).where(LessonSegment.lesson_id.in_(assignment))
    if lesson_id is not None:
        segments_query = segments_query.where(LessonSegment.lesson_id == lesson_id)
    segments = list(
        await session.scalars(
            segments_query.order_by(LessonSegment.lesson_id, LessonSegment.sequence_order)
        )
    )
    blocked = {row.lesson_id for row in segments if row.needs_review and row.approved_at is None}
    blocked.update(await outstanding_key_points(session, {row.lesson_id for row in segments}))
    targets = {}
    for segment in segments:
        if segment.lesson_id in blocked:
            continue
        keys = [segment.concept_id, (segment.calculation_variant or {}).get("conceptId")]
        keys.extend(item.get("conceptId") for item in segment.comprehension_checkpoints or [])
        for key in keys:
            try:
                concept_id = UUID(str(key))
            except (ValueError, TypeError):
                continue
            targets.setdefault(concept_id, segment)
    query = select(Concept).where(
        Concept.school_id == student.school_id,
        Concept.id.in_(targets),
    )
    if subject:
        query = query.where(Concept.subject.ilike(subject))
    concepts = list(await session.scalars(query.order_by(Concept.curriculum_position, Concept.id)))
    states = {
        row.concept_id: row
        for row in await session.scalars(
            select(StudentConceptMastery).where(StudentConceptMastery.student_id == student.id)
        )
    }
    mastered = {
        str(key)
        for key, row in states.items()
        if row.mastery_probability_concept >= MASTERY_THRESHOLD and row.practice_count >= 3
    }
    eligible = [
        concept for concept in concepts if set(concept.prerequisite_ids or []).issubset(mastered)
    ]
    due = list(
        await session.scalars(
            select(StudentConceptScheduling)
            .where(
                StudentConceptScheduling.student_id == student.id,
                StudentConceptScheduling.next_review_due <= now,
            )
            .order_by(StudentConceptScheduling.next_review_due)
        )
    )
    due_ids = {row.concept_id for row in due}
    completed_lessons = set(
        await session.scalars(
            select(LessonProgress.lesson_id).where(
                LessonProgress.student_id == student.id,
                LessonProgress.status == "completed",
            )
        )
    )
    review = next(
        (concept for schedule in due for concept in eligible if concept.id == schedule.concept_id),
        None,
    )
    pending = [
        concept
        for concept in eligible
        if str(concept.id) not in mastered
        and concept.id not in due_ids
        and targets[concept.id].lesson_id not in completed_lessons
    ]
    placements = (student.baseline_profile or {}).get("subject_placements") or {}
    concept = review
    if concept is None and pending:
        # Pick the first unmet concept at/after placement, never a prerequisite
        # the child has already demonstrated. Explicit school ordering wins.
        concept = min(
            pending,
            key=lambda item: (
                abs(
                    item.curriculum_position
                    - float(placements.get((item.subject or "").casefold(), 0))
                ),
                item.curriculum_position,
                str(item.id),
            ),
        )
    if concept is None:
        return None
    target = targets[concept.id]
    target_lesson_id = target.lesson_id
    lesson_segments = [row for row in segments if row.lesson_id == target_lesson_id]
    return {
        "lessonId": target_lesson_id,
        "conceptId": concept.id,
        "conceptName": concept.name,
        "segmentId": target.id,
        "segmentPosition": lesson_segments.index(target),
        "kind": "review" if review else "new_work",
    }
