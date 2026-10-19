"""Apply recall evidence in the lesson completion transaction, once per concept."""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from nevo.db.models.account import User
from nevo.db.models.frontend_support import Concept
from nevo.db.models.mastery import StudentConceptScheduling
from nevo.db.models.product import LessonQuestionAttempt
from nevo.db.models.review_evidence import ConceptReviewEvidence
from nevo.db.models.signal_event import LessonSession
from nevo.scheduler.entities import ConceptSchedule
from nevo.scheduler.fsrs import initial_schedule, update_schedule


async def record_session_reviews(session, student_id, session_id):
    # The same lock is held by answer/progress writes, including first-schedule creation.
    student = await session.get(User, student_id, with_for_update=True)
    sitting = await session.get(LessonSession, session_id)
    attempts = list(
        await session.scalars(
            select(LessonQuestionAttempt)
            .where(
                LessonQuestionAttempt.student_id == student_id,
                LessonQuestionAttempt.session_id == session_id,
                LessonQuestionAttempt.correct.is_not(None),
            )
            .order_by(LessonQuestionAttempt.submitted_at, LessonQuestionAttempt.id)
        )
    )
    groups = defaultdict(list)
    for attempt in attempts:
        key = attempt.question_snapshot.get("conceptId")
        if key:
            groups[UUID(str(key))].append(attempt)
    results = {}
    for concept_id, rows in groups.items():
        concept = await session.get(Concept, concept_id)
        if concept is None or concept.school_id != student.school_id:
            continue
        evidence = await session.scalar(
            select(ConceptReviewEvidence).where(
                ConceptReviewEvidence.student_id == student_id,
                ConceptReviewEvidence.concept_id == concept_id,
                ConceptReviewEvidence.session_id == session_id,
            )
        )
        if evidence is not None:
            results[concept_id] = evidence
            continue
        first, last = {}, {}
        for row in rows:
            first.setdefault(row.question_id, row)
            last[row.question_id] = row
        from nevo.intelligence.learning_runtime import minimum_reading_time

        unaided = all(
            row.correct is True
            and row.hint_count == 0
            and row.response_time_ms is not None
            and row.response_time_ms >= minimum_reading_time(row.question_snapshot)
            for row in first.values()
        ) and not any(row.hint_count > 0 for row in rows)
        outcome = (
            "first_time"
            if unaided
            else "after_hint"
            if any(row.hint_count for row in rows)
            else "second_attempt"
            if all(row.correct for row in last.values())
            else "not_recalled"
        )
        current = await session.scalar(
            select(StudentConceptScheduling)
            .where(
                StudentConceptScheduling.student_id == student_id,
                StudentConceptScheduling.concept_id == concept_id,
            )
            .with_for_update()
        )
        now = sitting.ended_at or datetime.now(UTC)
        # A schedule created by mastery earlier in this same sitting is a seed,
        # not a prior recall. Do not count the first lesson twice.
        prior = current is not None and current.last_review < rows[0].submitted_at
        stale = current is not None and current.last_review >= now
        if stale:
            schedule = ConceptSchedule(
                student_id=student_id,
                concept_id=concept_id,
                stability=current.stability,
                difficulty=current.difficulty,
                retrievability=1.0,
                last_review=current.last_review,
                review_count=current.review_count,
                next_review_due=current.next_review_due,
            )
        elif prior:
            schedule = update_schedule(
                current=ConceptSchedule(
                    student_id=student_id,
                    concept_id=concept_id,
                    stability=current.stability,
                    difficulty=current.difficulty,
                    retrievability=1.0,
                    last_review=current.last_review,
                    review_count=current.review_count,
                    next_review_due=current.next_review_due,
                ),
                recall_successful=unaided,
                reviewed_at=now,
            )
        else:
            schedule = initial_schedule(
                student_id=student_id,
                concept_id=concept_id,
                recall_successful=unaided,
                reviewed_at=now,
            )
        fields = {
            key: getattr(schedule, key)
            for key in ("stability", "difficulty", "last_review", "review_count", "next_review_due")
        }
        if current is None:
            session.add(
                StudentConceptScheduling(student_id=student_id, concept_id=concept_id, **fields)
            )
        else:
            for key, value in fields.items():
                setattr(current, key, value)
        snapshot = {
            "studentId": str(student_id),
            "conceptId": str(concept_id),
            "lessonId": str(rows[0].lesson_id),
            "retrievability": 1.0,
            "stability": schedule.stability,
            "difficulty": schedule.difficulty,
            "lastReview": schedule.last_review.isoformat(),
            "reviewCount": schedule.review_count,
            "nextReviewDue": schedule.next_review_due.isoformat(),
            "applied": not stale,
        }
        evidence = ConceptReviewEvidence(
            student_id=student_id,
            concept_id=concept_id,
            session_id=session_id,
            outcome=outcome,
            schedule_snapshot=snapshot,
        )
        session.add(evidence)
        results[concept_id] = evidence
    await session.flush()
    return results
