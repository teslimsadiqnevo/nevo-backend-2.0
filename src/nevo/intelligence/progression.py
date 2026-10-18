from datetime import UTC, datetime

from sqlalchemy import or_, select

from nevo.db.models.content import LessonSegment
from nevo.db.models.frontend_support import Concept, LessonAssignment
from nevo.db.models.mastery import StudentConceptMastery, StudentConceptScheduling
from nevo.intelligence.learning_runtime import MASTERY_THRESHOLD


async def next_work(session, student, subject=None, lesson_id=None):
    """Choose only assigned, available content with satisfied prerequisites."""
    now = datetime.now(UTC)
    assignment = select(LessonAssignment.lesson_id).where(
        LessonAssignment.student_id == student.id,
        LessonAssignment.status != "cancelled",
        or_(LessonAssignment.available_from.is_(None), LessonAssignment.available_from <= now),
    )
    mapped = select(LessonSegment.concept_id).where(LessonSegment.lesson_id.in_(assignment))
    query = select(Concept).where(
        Concept.school_id == student.school_id,
        or_(Concept.lesson_id.in_(assignment), Concept.id.in_(mapped)),
    )
    if subject:
        query = query.where(Concept.subject.ilike(subject))
    if lesson_id:
        query = query.where(
            or_(
                Concept.lesson_id == lesson_id,
                Concept.id.in_(
                    select(LessonSegment.concept_id).where(LessonSegment.lesson_id == lesson_id)
                ),
            )
        )
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
    review = next(
        (concept for schedule in due for concept in eligible if concept.id == schedule.concept_id),
        None,
    )
    pending = [
        concept
        for concept in eligible
        if str(concept.id) not in mastered and concept.id not in due_ids
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
    available_segments = list(
        await session.scalars(
            select(LessonSegment)
            .where(
                LessonSegment.lesson_id.in_(assignment),
                LessonSegment.concept_id == concept.id,
            )
            .order_by(LessonSegment.sequence_order)
        )
    )
    target_lesson_id = available_segments[0].lesson_id if available_segments else concept.lesson_id
    if lesson_id is not None:
        target_lesson_id = lesson_id
    segments = list(
        await session.scalars(
            select(LessonSegment)
            .where(
                LessonSegment.lesson_id == target_lesson_id,
            )
            .order_by(LessonSegment.sequence_order)
        )
    )
    target = next(
        (
            row
            for row in segments
            if row.concept_id == concept.id
            or str((row.calculation_variant or {}).get("conceptId")) == str(concept.id)
            or any(
                str(item.get("conceptId")) == str(concept.id)
                for item in row.comprehension_checkpoints or []
            )
        ),
        segments[0] if segments else None,
    )
    return {
        "lessonId": target_lesson_id,
        "conceptId": concept.id,
        "conceptName": concept.name,
        "segmentId": target.id if target else None,
        "segmentPosition": segments.index(target) if target else 0,
        "kind": "review" if review else "new_work",
    }
