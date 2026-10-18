"""Transactional links between onboarding, authored work and local intelligence."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.db.models.account import User
from nevo.db.models.frontend_support import Concept
from nevo.db.models.mastery import (
    ScaffoldProblemLog,
    StudentConceptMastery,
    StudentConceptScaffoldState,
    StudentConceptScheduling,
)
from nevo.db.models.product import LessonQuestionAttempt
from nevo.intelligence.entities import ScaffoldConceptState, ScaffoldProblemAttempt
from nevo.intelligence.scaffolds import ProgressiveScaffoldFadingEngine
from nevo.mastery.engine import HybridAktMasteryEngine, reading_seed_from_wpm
from nevo.mastery.entities import BaselineMasterySeed, MasteryState, MasteryUpdate
from nevo.scheduler.fsrs import initial_schedule

ONBOARDING_MODULES = ("grid_span", "pattern_flanker", "sentence_dot", "domain_probe")
MASTERY_THRESHOLD = 0.7


async def seed_completed_lesson_reviews(session, student_id, session_id):
    attempts = list(
        await session.scalars(
            select(LessonQuestionAttempt)
            .where(
                LessonQuestionAttempt.student_id == student_id,
                LessonQuestionAttempt.session_id == session_id,
                LessonQuestionAttempt.correct.is_not(None),
            )
            .order_by(LessonQuestionAttempt.submitted_at)
        )
    )
    outcomes = {}
    for attempt in attempts:
        key = (attempt.question_snapshot or {}).get("conceptId")
        if key:
            outcomes[UUID(str(key))] = bool(attempt.correct)
    existing = set(
        await session.scalars(
            select(StudentConceptScheduling.concept_id).where(
                StudentConceptScheduling.student_id == student_id,
                StudentConceptScheduling.concept_id.in_(outcomes),
            )
        )
    )
    valid = set(
        await session.scalars(
            select(Concept.id)
            .join(User, User.school_id == Concept.school_id)
            .where(User.id == student_id, Concept.id.in_(outcomes))
        )
    )
    for concept_id, successful in outcomes.items():
        if concept_id in existing or concept_id not in valid:
            continue
        schedule = initial_schedule(
            student_id=student_id,
            concept_id=concept_id,
            recall_successful=successful,
            reviewed_at=datetime.now(UTC),
        )
        session.add(
            StudentConceptScheduling(
                **{
                    name: getattr(schedule, name)
                    for name in (
                        "student_id",
                        "concept_id",
                        "stability",
                        "difficulty",
                        "last_review",
                        "review_count",
                        "next_review_due",
                    )
                }
            )
        )


def onboarding_modules(profile: dict) -> set[str]:
    return set(profile.get("completed_modules") or ()) & set(ONBOARDING_MODULES)


def require_onboarding(user: User) -> None:
    missing = [
        name
        for name in ONBOARDING_MODULES
        if name not in onboarding_modules(user.baseline_profile or {})
    ]
    if missing:
        raise HTTPException(
            409,
            detail={
                "code": "onboarding_required",
                "message": "Finish getting started before opening a lesson.",
                "missingModules": missing,
                "navigatesTo": "/student/onboarding",
            },
        )


def merge_baseline(previous: dict, current: dict, dimensions: set[str]) -> dict:
    completed = onboarding_modules(previous)
    if "wmc" in dimensions:
        completed.add("grid_span")
    if {"ps", "attention"}.issubset(dimensions):
        completed.add("pattern_flanker")
    if {"reading", "ans"}.issubset(dimensions):
        completed.add("sentence_dot")
    result = {**previous, **current, "completed_modules": sorted(completed)}
    if set(ONBOARDING_MODULES).issubset(completed):
        result.setdefault("onboarding_completed_at", datetime.now(UTC).isoformat())
    return result


async def ensure_prerequisites(
    session: AsyncSession, student_id: UUID, lesson_id: UUID, concept_id: UUID | None = None
) -> None:
    query = (
        select(Concept).where(Concept.id == concept_id)
        if concept_id
        else select(Concept).where(Concept.lesson_id == lesson_id)
    )
    concepts = list(await session.scalars(query))
    required = {UUID(value) for concept in concepts for value in (concept.prerequisite_ids or [])}
    if not required:
        return
    known = set(
        await session.scalars(
            select(StudentConceptMastery.concept_id).where(
                StudentConceptMastery.student_id == student_id,
                StudentConceptMastery.concept_id.in_(required),
                StudentConceptMastery.mastery_probability_concept >= MASTERY_THRESHOLD,
                StudentConceptMastery.practice_count >= 3,
            )
        )
    )
    eligible = any(
        set(concept.prerequisite_ids or []).issubset({str(value) for value in known})
        for concept in concepts
    )
    if required - known and not eligible:
        raise HTTPException(
            409,
            detail={
                "code": "prerequisite_work_required",
                "message": "There is an earlier idea to work through first.",
                "conceptIds": sorted(str(value) for value in required - known),
            },
        )


def minimum_reading_time(question: dict) -> int:
    text = str(question.get("prompt") or question.get("question") or "")
    options = question.get("options") or []
    text += " " + " ".join(
        str(option.get("label", "")) for option in options if isinstance(option, dict)
    )
    return max(800, min(15_000, len(text.split()) * 100))


async def apply_marked_attempt(
    session: AsyncSession, user: User, attempt: LessonQuestionAttempt
) -> None:
    """Run once in the answer transaction; retries return the existing attempt."""
    if attempt.correct is None:
        return
    question = attempt.question_snapshot
    concept_id = question.get("conceptId")
    if not concept_id:
        return
    concept = await session.get(Concept, UUID(str(concept_id)))
    if concept is None or concept.school_id != user.school_id:
        return
    row = await session.scalar(
        select(StudentConceptMastery)
        .where(
            StudentConceptMastery.student_id == user.id,
            StudentConceptMastery.concept_id == concept.id,
        )
        .with_for_update()
    )
    engine = HybridAktMasteryEngine()
    if row is None:
        placements = (user.baseline_profile or {}).get("subject_placements") or {}
        placement = placements.get((concept.subject or "").casefold(), 0.15)
        state = engine.initial_state(
            student_id=user.id,
            concept_id=concept.id,
            seed=BaselineMasterySeed(
                concept_probability=float(placement),
                reading_probability=reading_seed_from_wpm(
                    (user.baseline_profile or {}).get("reading_wpm"), age_band=user.age_band
                ),
                source="subject_probe"
                if (concept.subject or "").casefold() in placements
                else "baseline_profile",
            ),
        )
    else:
        state = MasteryState(
            **{
                name: getattr(row, name)
                for name in MasteryState.__dataclass_fields__
                if name != "concept_name"
            },
            concept_name=concept.name,
        )
    result = engine.update(
        state=state,
        interaction=MasteryUpdate(
            student_id=user.id,
            concept_id=concept.id,
            response_correct=attempt.correct,
            item_text_density=float(
                question.get("textDensity")
                if question.get("textDensity") is not None
                else (0.1 if question.get("answerType") == "numeric" else 0.8)
            ),
            response_time_ms=attempt.response_time_ms,
            minimum_response_time_ms=minimum_reading_time(question),
            hint_count=attempt.hint_count,
        ),
        related_mastery={},
    )
    values = {
        name: getattr(result.state, name)
        for name in MasteryState.__dataclass_fields__
        if name not in {"student_id", "concept_id", "concept_name"}
    }
    if row is None:
        row = StudentConceptMastery(student_id=user.id, concept_id=concept.id, **values)
        session.add(row)
    else:
        for name, value in values.items():
            setattr(row, name, value)
    trusted = (
        attempt.response_time_ms is not None
        and attempt.response_time_ms >= minimum_reading_time(question)
    )
    if attempt.correct and not trusted:
        return
    if attempt.source != "calculation" or question.get("calculationComplete") is True:
        await _scaffold_attempt(session, user.id, concept.id, attempt)
    if (
        result.state.mastery_probability_concept >= MASTERY_THRESHOLD
        and result.state.practice_count >= 3
    ):
        existing = await session.scalar(
            select(StudentConceptScheduling).where(
                StudentConceptScheduling.student_id == user.id,
                StudentConceptScheduling.concept_id == concept.id,
            )
        )
        if existing is None:
            schedule = initial_schedule(
                student_id=user.id,
                concept_id=concept.id,
                recall_successful=True,
                reviewed_at=datetime.now(UTC),
            )
            session.add(
                StudentConceptScheduling(
                    **{
                        name: getattr(schedule, name)
                        for name in (
                            "student_id",
                            "concept_id",
                            "stability",
                            "difficulty",
                            "last_review",
                            "review_count",
                            "next_review_due",
                        )
                    }
                )
            )


async def _scaffold_attempt(session, student_id, concept_id, attempt):
    problem_id = hashlib.sha256(f"{attempt.session_id}:{attempt.question_id}".encode()).hexdigest()
    recorded = await session.scalar(
        select(ScaffoldProblemLog.id).where(
            ScaffoldProblemLog.student_id == student_id,
            ScaffoldProblemLog.problem_id == problem_id,
        )
    )
    if recorded is not None:
        return
    row = await session.scalar(
        select(StudentConceptScaffoldState)
        .where(
            StudentConceptScaffoldState.student_id == student_id,
            StudentConceptScaffoldState.concept_id == concept_id,
        )
        .with_for_update()
    )
    engine = ProgressiveScaffoldFadingEngine()
    state = (
        ScaffoldConceptState(
            **{name: getattr(row, name) for name in ScaffoldConceptState.__dataclass_fields__}
        )
        if row
        else engine.initial_state(student_id=student_id, concept_id=concept_id)
    )
    decision = engine.record_attempt(
        state=state,
        attempt=ScaffoldProblemAttempt(
            student_id=student_id,
            concept_id=concept_id,
            problem_id=f"{attempt.session_id}:{attempt.question_id}",
            response_correct=bool(attempt.correct),
            response_time_ms=attempt.response_time_ms,
            hint_count=attempt.hint_count,
        ),
    )
    values = {
        name: getattr(decision.state, name)
        for name in ScaffoldConceptState.__dataclass_fields__
        if name not in {"student_id", "concept_id"}
    }
    if row is None:
        session.add(
            StudentConceptScaffoldState(student_id=student_id, concept_id=concept_id, **values)
        )
    else:
        for name, value in values.items():
            setattr(row, name, value)
    session.add(
        ScaffoldProblemLog(
            student_id=student_id,
            concept_id=concept_id,
            problem_id=problem_id,
            scaffold_intensity=decision.previous_intensity,
            next_scaffold_intensity=decision.next_intensity,
            outcome=decision.outcome,
            response_time_ms=attempt.response_time_ms,
            expected_response_time_ms=None,
            hint_count=attempt.hint_count,
            level_changed=decision.level_changed,
            change_reason=decision.change_reason,
        )
    )
