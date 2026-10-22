from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from nevo.db.models.account import User
from nevo.db.models.content import LessonSegment
from nevo.db.models.product import LessonQuestionAttempt
from nevo.db.models.signal_event import AdaptationDecision, SignalEvent
from nevo.intelligence.question_support import two_miss_hint
from tests.intelligence.test_learning_runtime_endpoints import adapt, answer, run, start
from tests.intelligence.test_learning_runtime_endpoints import runtime as runtime_fixture


@pytest.fixture(name="runtime")
def player_runtime(monkeypatch):
    yield from runtime_fixture.__wrapped__(monkeypatch)


def trial(correct, question="q", hint="Look at the equal parts."):
    return SimpleNamespace(correct=correct, question_id=question, question_snapshot={"hint": hint})


def test_hint_counts_only_this_question_and_no_declines_as_misses():
    latest = trial(False)
    assert two_miss_hint(latest, [latest]) is None
    assert two_miss_hint(latest, [latest, trial(False, "other")]) is None
    assert two_miss_hint(latest, [latest, trial(None)]) is None
    assert two_miss_hint(latest, [latest, trial(True), trial(False)]) is None
    assert (
        two_miss_hint(latest, [latest, trial(None), trial(False)])
        == latest.question_snapshot["hint"]
    )
    assert two_miss_hint(trial(False, hint=None), [latest, latest]) is None


def test_two_misses_offer_authored_hint_without_history_and_keep_credit_hinted(runtime):
    async def clear_history():
        async with runtime.sessions.begin() as session:
            student = await session.get(User, runtime.ids["student"])
            student.baseline_profile = {
                key: value
                for key, value in student.baseline_profile.items()
                if key in {"completed_modules", "subject_placements"}
            }
            student.age_band = "senior_secondary"

    run(clear_history())
    sitting = start(runtime)
    assert answer(runtime, sitting, 0).status_code == 201
    first = adapt(runtime, sitting)
    assert first.status_code == 200, first.text
    assert first.json()["proactiveAdjustment"] is None
    assert answer(runtime, sitting, 0).status_code == 201
    second = adapt(runtime, sitting)
    assert second.status_code == 200, second.text
    assert second.json()["proactiveAdjustment"]["action"] == "offer_hint"
    assert second.json()["proactiveAdjustment"]["hint"] == "Count the equal parts."
    assert second.json()["adjustmentDisposition"] == "apply"
    again = adapt(runtime, sitting)
    assert again.status_code == 200, again.text
    assert again.json()["adjustmentDisposition"] == "retain"
    assert again.json()["decisionId"] == second.json()["decisionId"]
    assert answer(runtime, sitting, 0).status_code == 201
    during_grace = adapt(runtime, sitting)
    assert during_grace.status_code == 200, during_grace.text
    assert during_grace.json()["supportGraceUntil"] is not None
    assert during_grace.json()["proactiveAdjustment"]["action"] == "offer_hint"
    correct = answer(runtime, sitting, 5)
    assert correct.status_code == 201, correct.text

    async def verify():
        async with runtime.sessions() as session:
            marked = await session.scalar(
                select(LessonQuestionAttempt).where(
                    LessonQuestionAttempt.session_id == UUID(sitting),
                    LessonQuestionAttempt.correct.is_(True),
                )
            )
            assert marked.hint_count >= 1
            decisions = list(
                await session.scalars(
                    select(AdaptationDecision).where(
                        AdaptationDecision.session_id == UUID(sitting),
                        AdaptationDecision.action == "offer_hint",
                    )
                )
            )
            assert len(decisions) == 1
            assert decisions[0].trigger_signals[0]["category"] == "question_support"

    run(verify())
    finished = adapt(runtime, sitting)
    assert finished.json()["proactiveAdjustment"] is None


@pytest.mark.parametrize("hint", [None, "", "   "])
def test_hint_is_not_replaced_by_another_steps_hint(runtime, hint):
    async def remove_question_hint():
        async with runtime.sessions.begin() as session:
            segment = await session.get(LessonSegment, runtime.ids["segment"])
            segment.comprehension_checkpoints = [
                {
                    **{key: value for key, value in item.items() if key != "hint"},
                    **({"hint": hint} if hint is not None else {}),
                }
                for item in segment.comprehension_checkpoints
            ]
            assert segment.calculation_variant["steps"][0]["hint"]

    run(remove_question_hint())
    sitting = start(runtime)
    for _ in range(2):
        assert answer(runtime, sitting, 0).status_code == 201
    response = adapt(runtime, sitting)
    assert response.status_code == 200, response.text
    assert response.json()["proactiveAdjustment"] is None


def test_question_hint_bypasses_adaptation_cooldown(runtime):
    sitting = start(runtime)
    for _ in range(2):
        assert answer(runtime, sitting, 0).status_code == 201

    async def decision():
        from datetime import UTC, datetime

        async with runtime.sessions.begin() as session:
            session.add(
                SignalEvent(
                    student_id=runtime.ids["student"],
                    session_id=UUID(sitting),
                    event_type="simplify_trigger",
                    timestamp=datetime.now(UTC),
                    event_data={"segmentId": str(runtime.ids["segment"])},
                )
            )

    run(decision())
    response = adapt(runtime, sitting)
    assert response.status_code == 200, response.text
    assert response.json()["proactiveAdjustment"]["action"] == "offer_hint"
