"""Transactional links between onboarding, authored work and local intelligence."""

import hashlib
from dataclasses import replace
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
    StudentConceptLevelMastery,
    StudentConceptScaffoldState,
    StudentConceptScheduling,
)
from nevo.db.models.product import LessonQuestionAttempt
from nevo.db.models.signal_event import LessonSession
from nevo.intelligence.entities import ScaffoldConceptState, ScaffoldProblemAttempt
from nevo.intelligence.scaffolds import ProgressiveScaffoldFadingEngine, initial_scaffold_intensity
from nevo.mastery.engine import HybridAktMasteryEngine, reading_seed_from_wpm
from nevo.mastery.entities import BaselineMasterySeed, MasteryState, MasteryUpdate
from nevo.scheduler.fsrs import initial_schedule

ONBOARDING_MODULES = ("grid_span", "pattern_flanker", "sentence_dot", "domain_probe")
MASTERY_THRESHOLD = 0.7


async def seed_completed_lesson_reviews(session, student_id, session_id):
    from nevo.intelligence.reviews import record_session_reviews

    return await record_session_reviews(session, student_id, session_id)


def onboarding_modules(profile: dict) -> set[str]:
    completed = set(profile.get("completed_modules") or ()) & set(ONBOARDING_MODULES)
    if profile.get("domain_probe_status") == "unavailable_at_onboarding":
        completed.add("domain_probe")
    return completed


async def onboarding_subjects(session: AsyncSession, user: User):
    from nevo.db.models.account import StudentClassEnrollment
    from nevo.db.models.probe import ProbeItem
    from nevo.db.models.subject import ClassSubject, SchoolSubject

    subjects = list(
        await session.scalars(
            select(SchoolSubject)
            .join(ClassSubject, ClassSubject.school_subject_id == SchoolSubject.id)
            .join(StudentClassEnrollment, StudentClassEnrollment.class_id == ClassSubject.class_id)
            .where(
                StudentClassEnrollment.student_id == user.id,
                SchoolSubject.school_id == user.school_id,
            )
            .distinct()
            .order_by(SchoolSubject.name)
        )
    )
    available = set(
        await session.scalars(
            select(ProbeItem.school_subject_id)
            .where(
                ProbeItem.school_id == user.school_id,
                ProbeItem.retired.is_(False),
                ProbeItem.school_subject_id.in_([subject.id for subject in subjects]),
            )
            .distinct()
        )
    )
    return subjects, available


async def refresh_onboarding(session: AsyncSession, user: User):
    """Record an explicit unmeasured outcome, never a fabricated placement."""
    subjects, available = await onboarding_subjects(session, user)
    profile = dict(user.baseline_profile or {})
    previous = dict(profile)
    if available and profile.get("domain_probe_status") == "unavailable_at_onboarding":
        profile["completed_modules"] = sorted(
            set(profile.get("completed_modules") or []) - {"domain_probe"}
        )
        profile["domain_probe_status"] = "pending_bank_available"
        profile.pop("onboarding_completed_at", None)
    if "domain_probe" not in onboarding_modules(profile) and not available:
        profile["domain_probe_status"] = "unavailable_at_onboarding"
        profile.setdefault("domain_probe_unavailable_at", datetime.now(UTC).isoformat())
    placements = profile.get("subject_placements") or {}
    statuses = dict(profile.get("subject_placement_statuses") or {})
    for subject in subjects:
        if (
            subject.id in available
            and statuses.get(str(subject.id), {}).get("reason") == "no_question_bank"
        ):
            statuses[str(subject.id)] = {"status": "unestablished", "reason": "probe_pending"}
        if (
            subject.id not in available
            and str(subject.id) not in placements
            and subject.name.casefold() not in placements
        ):
            statuses[str(subject.id)] = {"status": "unestablished", "reason": "no_question_bank"}
    if statuses:
        profile["subject_placement_statuses"] = statuses
    if profile != previous:
        user.baseline_profile = profile
        await session.flush()
    return subjects, available


async def ensure_onboarding(session: AsyncSession, user: User) -> None:
    await refresh_onboarding(session, user)
    require_onboarding(user)


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
    if attempt.correct and await session.scalar(
        select(LessonQuestionAttempt.id)
        .where(
            LessonQuestionAttempt.session_id == attempt.session_id,
            LessonQuestionAttempt.question_id == attempt.question_id,
            LessonQuestionAttempt.source == attempt.source,
            LessonQuestionAttempt.attempt_number < attempt.attempt_number,
            LessonQuestionAttempt.correct.is_(True),
        )
        .limit(1)
    ):
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
    effective_hints = max(attempt.hint_count, int(question.get("supportStatus") == "supported"))
    if question.get("calculationComplete") is True:
        parts = list(
            await session.scalars(
                select(LessonQuestionAttempt).where(
                    LessonQuestionAttempt.session_id == attempt.session_id,
                    LessonQuestionAttempt.segment_id == attempt.segment_id,
                    LessonQuestionAttempt.source == "calculation",
                )
            )
        )
        hints = {}
        for part in parts:
            hints[part.question_id] = max(hints.get(part.question_id, 0), part.hint_count)
        effective_hints = max(
            effective_hints,
            sum(hints.values()),
            int(
                any(
                    part.correct is False
                    or part.question_snapshot.get("supportStatus") == "supported"
                    for part in parts
                )
            ),
        )
    related_ids = tuple(UUID(value) for value in (concept.prerequisite_ids or []))
    related_mastery = {
        item.concept_id: item.mastery_probability_concept
        for item in await session.scalars(
            select(StudentConceptMastery)
            .join(Concept, Concept.id == StudentConceptMastery.concept_id)
            .where(
                StudentConceptMastery.student_id == user.id,
                StudentConceptMastery.concept_id.in_(related_ids),
                Concept.school_id == user.school_id,
            )
        )
    }
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
                else "unestablished_conservative",
            ),
            related_concept_ids=related_ids,
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
            hint_count=effective_hints,
            related_concept_ids=related_ids,
        ),
        related_mastery=related_mastery,
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
    level = question.get("masteryLevel")
    if (
        attempt.source in {"checkpoint", "assessment"}
        and level in {"knowledge", "application", "analysis"}
        and question.get("teacherReviewed") is True
    ):
        level_row = await session.scalar(
            select(StudentConceptLevelMastery)
            .where(
                StudentConceptLevelMastery.student_id == user.id,
                StudentConceptLevelMastery.concept_id == concept.id,
                StudentConceptLevelMastery.mastery_level == level,
            )
            .with_for_update()
        )
        prior = level_row.mastery_probability if level_row is not None else 0.15
        count = level_row.practice_count if level_row is not None else 0
        level_result = engine.update(
            state=replace(state, mastery_probability_concept=prior, practice_count=count),
            interaction=MasteryUpdate(
                student_id=user.id,
                concept_id=concept.id,
                response_correct=attempt.correct,
                item_text_density=float(question.get("textDensity") or 0.8),
                response_time_ms=attempt.response_time_ms,
                minimum_response_time_ms=minimum_reading_time(question),
                hint_count=effective_hints,
            ),
            related_mastery={},
        )
        supported = bool(effective_hints or question.get("supportStatus") == "supported")
        if level_row is None:
            level_row = StudentConceptLevelMastery(
                student_id=user.id,
                concept_id=concept.id,
                mastery_level=level,
                mastery_probability=prior,
                practice_count=0,
                supported_pass_count=0,
            )
            session.add(level_row)
        level_row.mastery_probability = level_result.state.mastery_probability_concept
        level_row.practice_count = level_result.state.practice_count
        level_row.supported_pass_count += int(attempt.correct and supported)
        level_row.last_response_correct = attempt.correct
    trusted = (
        attempt.response_time_ms is not None
        and attempt.response_time_ms >= minimum_reading_time(question)
    )
    if attempt.correct and not trusted:
        return
    if attempt.source != "calculation" or question.get("calculationComplete") is True:
        await _scaffold_attempt(session, user, concept.id, attempt)
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


async def _scaffold_attempt(session, user, concept_id, attempt):
    student_id = user.id
    problem_id = hashlib.sha256(f"{attempt.session_id}:{attempt.question_id}".encode()).hexdigest()
    recorded = await session.scalar(
        select(ScaffoldProblemLog.id).where(
            ScaffoldProblemLog.student_id == student_id,
            ScaffoldProblemLog.problem_id == problem_id,
        )
    )
    if recorded is not None:
        # Each distinct question contributes at most one independent success.
        # A later supported pass is still recorded, without awarding a new streak.
        previous = await session.get(ScaffoldProblemLog, recorded)
        if attempt.correct and previous and previous.outcome == "struggled":
            previous.outcome = "correct"
            previous.change_reason = "supported_pass"
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
    sitting = await session.get(LessonSession, attempt.session_id)
    config = (sitting.delivery_state or {}).get("engineConfig") if sitting else None
    config = config or user.engine_config or {}
    initial = initial_scaffold_intensity(config)
    state = (
        ScaffoldConceptState(
            **{name: getattr(row, name) for name in ScaffoldConceptState.__dataclass_fields__}
        )
        if row
        else ScaffoldConceptState(
            student_id=student_id, concept_id=concept_id, current_intensity=initial
        )
    )
    hint_count = attempt.hint_count
    independent = bool(attempt.correct) and attempt.attempt_number == 1
    if attempt.source == "calculation":
        steps = list(
            await session.scalars(
                select(LessonQuestionAttempt).where(
                    LessonQuestionAttempt.session_id == attempt.session_id,
                    LessonQuestionAttempt.segment_id == attempt.segment_id,
                    LessonQuestionAttempt.source == "calculation",
                )
            )
        )
        hints = {}
        for step in steps:
            hints[step.question_id] = max(hints.get(step.question_id, 0), step.hint_count)
        hint_count = sum(hints.values())
        independent = independent and not any(step.correct is False for step in steps)
    decision = engine.record_attempt(
        state=state,
        attempt=ScaffoldProblemAttempt(
            student_id=student_id,
            concept_id=concept_id,
            problem_id=f"{attempt.session_id}:{attempt.question_id}",
            response_correct=bool(attempt.correct),
            counts_as_independent=independent
            and attempt.question_snapshot.get("supportStatus") != "supported",
            response_time_ms=attempt.response_time_ms,
            hint_count=hint_count,
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
            hint_count=hint_count,
            level_changed=decision.level_changed,
            change_reason=decision.change_reason,
        )
    )
