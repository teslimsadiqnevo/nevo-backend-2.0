from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select

from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.frontend_support import Concept, LessonAssignment
from nevo.db.models.product import LessonProgress, LessonQuestionAttempt
from nevo.db.models.mastery import (
    StudentConceptLevelMastery, StudentConceptMastery, StudentConceptScheduling,
)
from nevo.intelligence.learning_runtime import MASTERY_THRESHOLD

LEVEL_INDEPENDENT_PASSES = 2


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
    levels = {
        (row.concept_id, row.mastery_level): row
        for row in await session.scalars(
            select(StudentConceptLevelMastery).where(
                StudentConceptLevelMastery.student_id == student.id,
                StudentConceptLevelMastery.concept_id.in_(due_ids),
            )
        )
    }
    review = None
    review_item = None
    lesson_cache = {}
    for schedule in due:
        candidate = next((item for item in eligible if item.id == schedule.concept_id), None)
        if candidate is None:
            continue
        candidate_segments = [row for row in segments if row.lesson_id not in blocked]
        candidate_item = await _due_item(
            session, student.id, candidate.id, candidate_segments, levels
        )
        if candidate_item is None:
            # No approved, fresh higher-level item: leave the due date in place.
            # Do not repeat the same answer and call that transfer.
            has_level_content = any(
                question.get("masteryLevel") in {"knowledge", "application", "analysis"}
                and str(question.get("conceptId") or row.concept_id) == str(candidate.id)
                for row in candidate_segments
                for question in row.comprehension_checkpoints or []
            )
            for row in candidate_segments:
                if row.lesson_id not in lesson_cache:
                    lesson_cache[row.lesson_id] = await session.get(Lesson, row.lesson_id)
                lesson = lesson_cache[row.lesson_id]
                if lesson and any(
                    item.get("masteryLevel") in {"knowledge", "application", "analysis"}
                    and str(item.get("conceptId")) == str(candidate.id)
                    for item in lesson.assessment or []
                ):
                    has_level_content = True
                    break
            if any(key[0] == candidate.id for key in levels) or has_level_content:
                continue
            review = candidate  # Legacy lessons retain their existing return route.
            break
        review, review_item = candidate, candidate_item
        break
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
    target = review_item[0] if review_item else targets[concept.id]
    target_lesson_id = target.lesson_id
    lesson_segments = [row for row in segments if row.lesson_id == target_lesson_id]
    result = {
        "lessonId": target_lesson_id,
        "conceptId": concept.id,
        "conceptName": concept.name,
        "segmentId": target.id,
        "segmentPosition": lesson_segments.index(target),
        "kind": "review" if review else "new_work",
    }
    if review_item:
        result["reviewQuestionId"] = str(review_item[1]["id"])
    return result


async def _due_item(session, student_id, concept_id, segments, levels):
    from nevo.api.lesson_review import approved_check_ids

    order = ("knowledge", "application", "analysis")
    target_level = next((
        level for level in order
        if not (
            (state := levels.get((concept_id, level)))
            and state.mastery_probability >= MASTERY_THRESHOLD
            and state.independent_pass_count >= LEVEL_INDEPENDENT_PASSES
        )
    ), None)
    if target_level is None:
        return None
    seen = set(await session.scalars(
        select(LessonQuestionAttempt.question_id).where(
            LessonQuestionAttempt.student_id == student_id,
            LessonQuestionAttempt.question_snapshot["conceptId"].astext == str(concept_id),
        )
    ))
    approvals = {}
    lessons = {}
    by_id = {str(segment.id): segment for segment in segments}
    for segment in segments:
        for question in segment.comprehension_checkpoints or []:
            question_id = str(question.get("id") or "")
            if (
                question.get("masteryLevel") != target_level
                or str(question.get("conceptId") or segment.concept_id) != str(concept_id)
                or question.get("answerKey") is None
                or question_id in seen
            ):
                continue
            if segment.lesson_id not in approvals:
                approvals[segment.lesson_id] = await approved_check_ids(session, segment.lesson_id)
            if (
                (str(segment.id), question_id) in approvals[segment.lesson_id]
            ):
                return segment, question
    for segment in segments:
        if segment.lesson_id not in lessons:
            lessons[segment.lesson_id] = await session.get(Lesson, segment.lesson_id)
        lesson = lessons[segment.lesson_id]
        if lesson is None:
            continue
        for question in lesson.assessment or []:
            question_id = str(question.get("id") or "")
            if (
                question.get("masteryLevel") != target_level
                or str(question.get("conceptId")) != str(concept_id)
                or str(question.get("sourceSegmentId")) not in by_id
                or question.get("answerKey") is None
                or question_id in seen
            ):
                continue
            if segment.lesson_id not in approvals:
                approvals[segment.lesson_id] = await approved_check_ids(session, segment.lesson_id)
            if ("assessment", question_id) in approvals[segment.lesson_id]:
                return by_id[str(question["sourceSegmentId"])], question
    return None
