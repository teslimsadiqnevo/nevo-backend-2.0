from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from nevo.db.models.signal_event import AdaptationDecision, LessonSession, SignalEvent
from nevo.domain.signal_events.vocabulary import SignalEventType as Event
from nevo.intelligence.question_support import guidance_deadline
from nevo.intelligence.runtime_evidence import engagement, engagement_decline_seconds
from tests.intelligence.test_learning_runtime_endpoints import adapt, answer, run, start
from tests.intelligence.test_learning_runtime_endpoints import runtime as runtime_fixture


@pytest.fixture(name="runtime")
def player_runtime(monkeypatch):
    yield from runtime_fixture.__wrapped__(monkeypatch)


def test_transaction_mode_keeps_client_connections_without_prepared_cache_buildup(
    runtime, monkeypatch
):
    from sqlalchemy import text

    from nevo.db.session import create_engine
    from tests.intelligence.test_learning_runtime_endpoints import URL

    monkeypatch.setattr("nevo.db.session._is_transaction_pooler", lambda _: True)

    async def exercise():
        engine = create_engine(URL)
        try:
            async with engine.connect() as connection:
                first = await connection.scalar(text("select pg_backend_pid()"))
                baseline = await connection.scalar(
                    text("select count(*) from pg_prepared_statements")
                )
                for index in range(40):
                    assert await connection.scalar(text(f"select {index}")) == index
                after = await connection.scalar(text("select count(*) from pg_prepared_statements"))
                assert after <= baseline + 2
            async with engine.connect() as connection:
                assert await connection.scalar(text("select pg_backend_pid()")) == first
        finally:
            await engine.dispose()

    run(exercise())


def test_cooldown_retains_help_until_the_question_is_solved(runtime):
    sitting = start(runtime)
    for _ in range(2):
        assert answer(runtime, sitting, 0).status_code == 201
    first = adapt(runtime, sitting)
    assert first.status_code == 200, first.text
    assert first.json()["adjustmentDisposition"] == "apply"
    assert first.json()["proactiveAdjustment"]["action"] == "offer_hint"

    async def offered():
        async with runtime.sessions.begin() as session:
            session.add(
                SignalEvent(
                    student_id=runtime.ids["student"],
                    session_id=UUID(sitting),
                    event_type=Event.HINT_OFFERED,
                    timestamp=datetime.now(UTC),
                    event_data={"segmentId": str(runtime.ids["segment"])},
                )
            )

    run(offered())
    held = adapt(runtime, sitting)
    assert held.status_code == 200, held.text
    assert held.json()["suppressedAttempt"]["reason"] == "adaptation_cooldown"
    assert held.json()["adjustmentDisposition"] == "retain"
    assert held.json()["proactiveAdjustment"] == first.json()["proactiveAdjustment"]
    assert held.json()["decisionId"] == first.json()["decisionId"]
    assert held.json()["cooldownUntil"]

    async def no_duplicate():
        async with runtime.sessions() as session:
            rows = list(
                await session.scalars(
                    select(AdaptationDecision).where(AdaptationDecision.session_id == UUID(sitting))
                )
            )
            assert len(rows) == 1

    run(no_duplicate())
    assert answer(runtime, sitting, 5).status_code == 201
    solved = adapt(runtime, sitting)
    assert solved.status_code == 200, solved.text
    assert solved.json()["adjustmentDisposition"] == "clear"
    assert solved.json()["proactiveAdjustment"] is None
    assert solved.json()["segments"][0]["densityScope"] == "segment"


def test_ended_sitting_choices_do_not_leak_into_lesson_reads(runtime):
    sitting = start(runtime)
    lesson, segment = runtime.ids["lesson"], runtime.ids["segment"]
    saved = runtime.client.put(
        f"/api/v1/lessons/{lesson}/sessions/{sitting}/segments/{segment}/preferences",
        json={"slower": True},
    )
    assert saved.status_code == 200, saved.text
    left = runtime.client.put(
        f"/api/v1/lessons/{lesson}/progress", json={"sessionId": sitting, "status": "exited"}
    )
    assert left.status_code == 200, left.text
    for url in (
        f"/api/v1/lessons/{lesson}",
        f"/api/content/lessons/{lesson}",
        f"/api/v1/lessons/{lesson}/offline-package.json",
    ):
        response = runtime.client.get(url)
        assert response.status_code == 200, response.text
        assert response.json()["segments"][0]["deliveryPreference"] is None
    resumed = runtime.client.post(f"/api/v1/lessons/{lesson}/session")
    assert resumed.status_code == 201, resumed.text
    assert resumed.json()["sessionId"] != sitting
    assert not resumed.json()["deliveryState"].get("segmentChoices")


def test_break_decline_is_read_and_stops_immediate_repeat_offers(runtime):
    sitting = start(runtime)

    async def decline():
        async with runtime.sessions.begin() as session:
            row = await session.get(LessonSession, UUID(sitting))
            row.started_at = datetime.now(UTC) - timedelta(minutes=25)
            session.add(
                SignalEvent(
                    student_id=runtime.ids["student"],
                    session_id=UUID(sitting),
                    event_type=Event.BREAK_DECLINED,
                    timestamp=datetime.now(UTC),
                    event_data={"breakType": "movement", "trigger": "engine_offer"},
                )
            )

    run(decline())
    result = adapt(runtime, sitting)
    assert result.status_code == 200, result.text
    assert result.json()["breakSuggestion"]["breakType"] is None
    assert result.json()["breakSuggestion"]["suppressedReason"] == "break_declined"
    assert result.json()["breakSuggestion"]["retryAt"]

    async def start_break():
        async with runtime.sessions.begin() as session:
            session.add(
                SignalEvent(
                    student_id=runtime.ids["student"],
                    session_id=UUID(sitting),
                    event_type=Event.BREAK_START,
                    timestamp=datetime.now(UTC),
                    event_data={"breakType": "movement", "trigger": "engine_offer"},
                )
            )

    run(start_break())
    active = adapt(runtime, sitting)
    assert active.status_code == 200, active.text
    assert active.json()["breakSuggestion"]["suppressedReason"] == "break_in_progress"
    assert active.json()["breakSuggestion"]["breakType"] is None


def test_engagement_decline_can_use_permitted_interruption_events_not_raw_touch():
    now = datetime.now(UTC)
    events = [
        SimpleNamespace(
            event_type=Event.ENGAGEMENT_SIGNAL,
            timestamp=now - timedelta(seconds=200 - index * 10),
            event_data={"indicator": indicator, "value": value},
        )
        for index in range(21)
        for indicator, value in (("task_switch", 1), ("return_after_pause", 10000))
    ]
    assert engagement_decline_seconds(events, 1.0, now) == 180
    assert engagement_decline_seconds(events, None, now) == 0
    pauses = [row for row in events if row.event_data["indicator"] == "return_after_pause"]
    assert engagement(pauses) is None
    assert engagement_decline_seconds(pauses, 1.0, now) == 0
    assert engagement_decline_seconds(events, 1.0, now + timedelta(seconds=31)) == 0


def test_engine_emits_engagement_decline_from_sustained_stored_evidence(runtime):
    sitting = start(runtime)
    now = datetime.now(UTC)

    async def seed():
        async with runtime.sessions.begin() as session:
            row = await session.get(LessonSession, UUID(sitting))
            row.started_at = now - timedelta(minutes=12)
            session.add(
                SignalEvent(
                    student_id=runtime.ids["student"],
                    session_id=UUID(sitting),
                    event_type=Event.ENGAGEMENT_SIGNAL,
                    timestamp=now - timedelta(minutes=10),
                    event_data={"indicator": "steady_progress", "value": 60000},
                )
            )
            for index in range(21):
                for indicator, value in (("task_switch", 1), ("return_after_pause", 10000)):
                    session.add(
                        SignalEvent(
                            student_id=runtime.ids["student"],
                            session_id=UUID(sitting),
                            event_type=Event.ENGAGEMENT_SIGNAL,
                            timestamp=now - timedelta(seconds=200 - index * 10),
                            event_data={"indicator": indicator, "value": value},
                        )
                    )

    run(seed())
    response = adapt(runtime, sitting)
    assert response.status_code == 200, response.text
    assert "engagement_decline" in response.json()["breakSuggestion"]["triggeredThresholds"]


@pytest.mark.parametrize(
    "band,seconds",
    [("early_primary", 45), ("junior_secondary", 60), ("senior_secondary", 90), (None, 90)],
)
def test_question_guidance_has_age_band_grace_without_a_fabricated_measurement(band, seconds):
    now = datetime.now(UTC)
    attempts = [
        SimpleNamespace(question_id="q", correct=False, submitted_at=now - timedelta(seconds=index))
        for index in range(3)
    ]
    student = SimpleNamespace(age_band=band, date_of_birth=None)
    assert guidance_deadline(attempts, student) == now - timedelta(seconds=2) + timedelta(
        seconds=seconds
    )
    attempts[0].correct = True
    assert guidance_deadline(attempts, student) is None
