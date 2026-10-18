"""The domain probe, served one item at a time.

The answer key never reaches the device. The client asks for the next item,
sends back what the child picked, and is told whether the probe is finished -
never which option was right. A probe whose key is on the device measures a
child's willingness to read the source, which is not what it is for.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.consent import StudentLearningConsent
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import actor_user
from nevo.api.response_models import CamelResponse
from nevo.db.models.probe import ProbeItem, ProbeResponse
from nevo.db.models.subject import SchoolSubject
from nevo.probe.selection import (
    MAX_QUESTIONS,
    STARTING_DIFFICULTY,
    STARTING_STEP,
    ProbeState,
    after,
    choose,
    entry_point,
    recalibrate,
    start,
)

router = APIRouter(prefix="/api/v1", tags=["intelligence"])


class ProbeOption(CamelResponse):
    value: str
    label: str


class ProbeQuestion(CamelResponse):
    """One item, as a child sees it. No answer, by construction."""

    subject_id: UUID
    item_id: UUID
    question: str
    options: list[ProbeOption]
    #: Which question this is, so a screen can say "3 of about 6" without
    #: promising an exact count the adaptation may not need.
    asked: int
    max_questions: int = MAX_QUESTIONS


class ProbeFinished(CamelResponse):
    """The probe's whole output: where to start this child in this subject."""

    finished: bool = True
    subject_id: UUID
    #: 0 to 1, bounded away from certainty at both ends. The starting mastery
    #: estimate the knowledge graph is seeded with.
    entry_point: float
    asked: int


class ProbeEmpty(CamelResponse):
    """A subject with no items yet.

    Said cleanly rather than by failing: items are generated from the lessons
    teachers upload, so a subject nobody has uploaded to has none, and that is
    an ordinary state the front end draws.
    """

    finished: bool = True
    no_items: bool = True
    subject_id: UUID


class ProbeAnswer(BaseModel):
    model_config = CAMEL_CONFIG

    item_id: UUID
    chosen_option: str = Field(min_length=1, max_length=80)


async def _state(session: DatabaseSession, *, student_id: UUID, subject_id: UUID) -> ProbeState:
    """Where this child's run has got to, recomputed from their answers.

    Derived rather than stored, so a run interrupted by a flat battery picks up
    exactly where it was instead of starting again.
    """

    rows = (
        await session.execute(
            select(ProbeResponse.correct)
            .where(
                ProbeResponse.student_id == student_id,
                ProbeResponse.school_subject_id == subject_id,
            )
            .order_by(ProbeResponse.answered_at)
        )
    ).all()
    state = start()
    for (correct,) in rows:
        if correct is not None:
            state = after(state, correct=correct)
    return state


async def _asked(session: DatabaseSession, *, student_id: UUID, subject_id: UUID) -> set[UUID]:
    rows = await session.execute(
        select(ProbeResponse.probe_item_id).where(
            ProbeResponse.student_id == student_id,
            ProbeResponse.school_subject_id == subject_id,
        )
    )
    return {row[0] for row in rows}


async def _finish(session, student, result):
    from datetime import UTC, datetime

    from nevo.intelligence.learning_runtime import ONBOARDING_MODULES, onboarding_modules

    baseline = dict(student.baseline_profile or {})
    state = await _state(session, student_id=student.id, subject_id=result.subject_id)
    if state.asked:
        subject = await session.get(SchoolSubject, result.subject_id)
        placements = dict(baseline.get("subject_placements") or {})
        placements[str(result.subject_id)] = result.entry_point
        placements[subject.name.casefold()] = result.entry_point
        baseline["subject_placements"] = placements
    baseline["domain_probe_status"] = (
        "completed" if state.asked else "completed_without_scored_answers"
    )
    completed = onboarding_modules(baseline) | {"domain_probe"}
    baseline["completed_modules"] = sorted(completed)
    if set(ONBOARDING_MODULES).issubset(completed):
        baseline.setdefault("onboarding_completed_at", datetime.now(UTC).isoformat())
    student.baseline_profile = baseline
    await session.commit()
    return result


@router.get(
    "/probe/{subject_id}/next",
    response_model=ProbeQuestion | ProbeFinished | ProbeEmpty,
)
async def next_question(
    subject_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
) -> ProbeQuestion | ProbeFinished | ProbeEmpty:
    """The next item for this child in this subject, or what the probe concluded."""

    student = await actor_user(session, principal)
    if student.role != "student":
        raise HTTPException(403, detail="Student account required")
    subject = await session.get(SchoolSubject, subject_id)
    if subject is None or subject.school_id != student.school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

    state = await _state(session, student_id=student.id, subject_id=subject_id)
    available = (
        await session.execute(
            select(ProbeItem.id, ProbeItem.difficulty).where(
                ProbeItem.school_subject_id == subject_id,
                ProbeItem.retired.is_(False),
            )
        )
    ).all()
    if not available:
        from nevo.intelligence.learning_runtime import refresh_onboarding

        await refresh_onboarding(session, student)
        await session.commit()
        return ProbeEmpty(subject_id=subject_id)
    if state.finished:
        return await _finish(
            session,
            student,
            ProbeFinished(
                subject_id=subject_id,
                entry_point=entry_point(state),
                asked=state.asked,
            ),
        )

    asked = await _asked(session, student_id=student.id, subject_id=subject_id)
    if len(asked) >= MAX_QUESTIONS:
        return await _finish(
            session,
            student,
            ProbeFinished(subject_id=subject_id, entry_point=entry_point(state), asked=len(asked)),
        )
    pool: list[tuple[object, float]] = [(row[0], row[1]) for row in available]
    chosen = choose(state, available=pool, already_asked=set(asked))
    if chosen is None:
        # The bank is exhausted before the run converged. Placing the child on
        # what we have is better than asking a question twice.
        return await _finish(
            session,
            student,
            ProbeFinished(
                subject_id=subject_id,
                entry_point=entry_point(state),
                asked=state.asked,
            ),
        )
    item = await session.get(ProbeItem, chosen)
    assert item is not None
    return ProbeQuestion(
        subject_id=subject_id,
        item_id=item.id,
        question=item.question,
        options=[
            ProbeOption(value=str(option.get("value")), label=str(option.get("label")))
            for option in item.options
        ],
        asked=len(asked) + 1,
    )


@router.post("/probe/{subject_id}/answer", response_model=ProbeQuestion | ProbeFinished)
async def submit_answer(
    subject_id: UUID,
    payload: ProbeAnswer,
    principal: PrincipalDependency,
    session: DatabaseSession,
    consent: StudentLearningConsent = None,
) -> ProbeQuestion | ProbeFinished:
    """Record what the child picked, and hand back the next item.

    The response never says whether they were right. The probe is a placement,
    and telling a child they got one wrong partway through changes how they
    answer the rest of it.
    """

    student = await actor_user(session, principal)
    if student.role != "student":
        raise HTTPException(403, detail="Student account required")
    await session.refresh(student, with_for_update=True)
    item = await session.get(ProbeItem, payload.item_id)
    if item is None or item.school_subject_id != subject_id or item.school_id != student.school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    declined = payload.chosen_option == "not_sure"
    if not declined and payload.chosen_option not in {
        str(option.get("value")) for option in item.options
    }:
        raise HTTPException(422, detail="Choose one of the supplied options")
    if item.id in await _asked(session, student_id=student.id, subject_id=subject_id):
        return await next_question(subject_id, principal, session)
    expected = await next_question(subject_id, principal, session)
    if isinstance(expected, ProbeFinished):
        return expected
    if not isinstance(expected, ProbeQuestion) or expected.item_id != item.id:
        raise HTTPException(
            409, detail={"code": "probe_item_stale", "message": "Read the current question again."}
        )
    correct = None if declined else payload.chosen_option == item.correct_option
    session.add(
        ProbeResponse(
            student_id=student.id,
            school_subject_id=subject_id,
            probe_item_id=item.id,
            chosen_option=payload.chosen_option,
            correct=correct,
            difficulty_at_the_time=item.difficulty,
        )
    )
    # Difficulty is learned from how children actually answer, so every answer
    # moves it - weighted so one run cannot rewrite a well-sat item.
    if correct is not None:
        item.times_answered += 1
        item.times_correct += int(correct)
        item.difficulty = recalibrate(
            item.difficulty,
            times_answered=item.times_answered,
            times_correct=item.times_correct,
        )
    await session.flush()
    result = await next_question(subject_id, principal, session)
    await session.commit()
    return result  # type: ignore[return-value]


__all__ = ["STARTING_DIFFICULTY", "STARTING_STEP", "router"]
