import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.api.product_learning import ProgressWrite, save_lesson_progress
from nevo.auth.entities import AuthPrincipal
from nevo.db.models.product import LessonProgress
from nevo.db.models.signal_event import LessonSession
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus, SignalEventType
from nevo.signal_events.entities import (
    LessonSessionSnapshot,
    SignalEventDraft,
    SignalIngestionBatch,
)
from nevo.signal_events.repositories import SqlAlchemySignalIngestionRepository
from tests.intelligence.test_learning_runtime_endpoints import answer, run, start
from tests.intelligence.test_learning_runtime_endpoints import runtime as runtime_fixture


@pytest.fixture(name="runtime")
def player_runtime(monkeypatch):
    yield from runtime_fixture.__wrapped__(monkeypatch)


def stale_batch(runtime, sitting):
    return SignalIngestionBatch(
        session=LessonSessionSnapshot(
            id=UUID(sitting),
            student_id=runtime.ids["student"],
            lesson_id=runtime.ids["lesson"],
            started_at=datetime.now(UTC),
            ended_at=None,
            completion_status=LessonCompletionStatus.IN_PROGRESS,
            exit_position=None,
            break_count=0,
            proactive_adjustments_count=0,
        ),
        events=(
            SignalEventDraft(
                student_id=runtime.ids["student"],
                session_id=UUID(sitting),
                event_type=SignalEventType.TIME_ON_SEGMENT,
                event_data={},
                timestamp=datetime.now(UTC),
            ),
        ),
    )


def test_late_signal_batch_cannot_reopen_completed_sitting(runtime):
    sitting = start(runtime)
    assert answer(runtime, sitting, 5).status_code == 201
    response = runtime.client.put(
        f"/api/v1/lessons/{runtime.ids['lesson']}/progress",
        json={"sessionId": sitting, "status": "completed"},
    )
    assert response.status_code == 200, response.text

    async def verify():
        await SqlAlchemySignalIngestionRepository(runtime.sessions).ingest(
            stale_batch(runtime, sitting)
        )
        async with runtime.sessions() as session:
            saved = await session.get(LessonSession, UUID(sitting))
            assert saved.completion_status == "completed" and saved.ended_at is not None

    run(verify())
    review = runtime.client.post(f"/api/v1/lessons/{runtime.ids['lesson']}/session")
    assert review.status_code == 201, review.text
    assert review.json()["reviewMode"] is True


def test_existing_completed_progress_recovers_its_reopened_sitting(runtime):
    sitting = start(runtime)
    assert answer(runtime, sitting, 5).status_code == 201
    response = runtime.client.put(
        f"/api/v1/lessons/{runtime.ids['lesson']}/progress",
        json={"sessionId": sitting, "status": "completed"},
    )
    assert response.status_code == 200

    async def damage():
        async with runtime.sessions.begin() as session:
            saved = await session.get(LessonSession, UUID(sitting))
            saved.completion_status = "in_progress"
            saved.ended_at = None

    run(damage())
    review = runtime.client.post(f"/api/v1/lessons/{runtime.ids['lesson']}/session")
    assert review.status_code == 201, review.text
    assert review.json()["sessionId"] == sitting
    assert review.json()["reviewMode"] is True


def test_partial_progress_save_keeps_existing_cursor(runtime):
    sitting = start(runtime)
    url = f"/api/v1/lessons/{runtime.ids['lesson']}/progress"
    saved = runtime.client.put(
        url, json={"sessionId": sitting, "segmentPosition": 3, "status": "in_progress"}
    )
    assert saved.status_code == 200, saved.text
    partial = runtime.client.put(
        url, json={"sessionId": sitting, "checkPosition": 1, "status": "in_progress"}
    )
    assert partial.status_code == 200, partial.text
    assert partial.json()["segmentPosition"] == 3


def test_concurrent_progress_adapt_and_signal_flushes(runtime):
    sitting = start(runtime)
    for _ in range(2):
        assert answer(runtime, sitting, 0).status_code == 201

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime.client.app), base_url="http://test"
        ) as client:
            for _ in range(2):
                tasks = []
                for _ in range(6):
                    tasks.extend(
                        [
                            client.put(
                                f"/api/v1/lessons/{runtime.ids['lesson']}/progress",
                                json={
                                    "sessionId": sitting,
                                    "segmentPosition": 0,
                                    "status": "in_progress",
                                },
                            ),
                            client.post(
                                "/api/intelligence/adapt",
                                json={
                                    "lessonId": str(runtime.ids["lesson"]),
                                    "sessionId": sitting,
                                    "mode": "in_lesson",
                                    "segments": [
                                        {
                                            "id": str(runtime.ids["segment"]),
                                            "segmentType": "explanation",
                                            "availableModalities": ["text"],
                                        }
                                    ],
                                    "signals": {"currentSegmentId": str(runtime.ids["segment"])},
                                },
                            ),
                            SqlAlchemySignalIngestionRepository(runtime.sessions).ingest(
                                stale_batch(runtime, sitting)
                            ),
                        ]
                    )
                results = await asyncio.wait_for(asyncio.gather(*tasks), 30)
                for response in results:
                    if response is not None:
                        assert response.status_code == 200, response.text

    run(scenario())


@pytest.mark.parametrize("legacy_lock", [True, False])
def test_progress_and_signal_flush_lock_interleaving(runtime, legacy_lock):
    sitting = start(runtime)

    async def scenario():
        user_locked, sitting_locked = asyncio.Event(), asyncio.Event()

        class PlayerSession(AsyncSession):
            async def refresh(self, instance, **kwargs):
                assert kwargs["with_for_update"] == {"key_share": True}
                if legacy_lock:
                    kwargs["with_for_update"] = True
                await super().refresh(instance, **kwargs)
                user_locked.set()
                await sitting_locked.wait()

        class SignalSession(AsyncSession):
            async def scalar(self, statement, *args, **kwargs):
                if getattr(getattr(statement, "table", None), "name", None) == "lesson_sessions":
                    await super().scalar(
                        select(LessonSession)
                        .where(LessonSession.id == UUID(sitting))
                        .with_for_update()
                    )
                    sitting_locked.set()
                return await super().scalar(statement, *args, **kwargs)

        engine = runtime.sessions.kw["bind"]
        player_sessions = async_sessionmaker(engine, class_=PlayerSession, expire_on_commit=False)
        signal_sessions = async_sessionmaker(engine, class_=SignalSession, expire_on_commit=False)

        async def save():
            async with player_sessions() as session:
                return await save_lesson_progress(
                    runtime.ids["lesson"],
                    ProgressWrite(sessionId=sitting, segmentPosition=0, status="in_progress"),
                    AuthPrincipal(runtime.ids["student"], "student", uuid4()),
                    session,
                    SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
                )

        async def flush():
            await user_locked.wait()
            await SqlAlchemySignalIngestionRepository(signal_sessions).ingest(
                stale_batch(runtime, sitting)
            )

        results = await asyncio.wait_for(
            asyncio.gather(save(), flush(), return_exceptions=True), 10
        )
        failures = [item for item in results if isinstance(item, Exception)]
        if legacy_lock:
            assert any(
                isinstance(item, DBAPIError) and "deadlock" in str(item).lower()
                for item in failures
            ), failures
        else:
            assert not failures, failures
            async with runtime.sessions() as session:
                progress = await session.scalar(
                    select(LessonProgress).where(
                        LessonProgress.student_id == runtime.ids["student"],
                        LessonProgress.lesson_id == runtime.ids["lesson"],
                    )
                )
                assert progress.session_id == UUID(sitting)

    run(scenario())
