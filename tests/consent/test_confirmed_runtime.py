"""HTTP consent enforcement with real learning writes on a disposable database."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from nevo.api.ask_nevo import router as ask_router
from nevo.api.consent import require_learning_consent_if_student
from nevo.api.consent import router as consent_router
from nevo.api.intelligence import get_scaffold_fading_service
from nevo.api.signals import router as signals_router
from nevo.consent.entities import ConsentRecordView
from nevo.consent.service import ConsentService
from nevo.db.models.account import ConsentRecord, User
from nevo.db.models.product import LessonProgress, LessonQuestionAttempt, PostLessonProcessing
from nevo.db.models.signal_event import LessonSession
from nevo.domain.accounts.vocabulary import ConsentStatus, ConsentType
from nevo.learner_profiles.post_lesson_worker import PostLessonProcessingWorker
from nevo.signal_events.service import SignalIngestionService
from tests.ask_nevo.test_api import FakeAskNevoService
from tests.consent.fakes import FixedConsentTokenService, MemoryConsentRepository
from tests.intelligence.test_learning_runtime_endpoints import (
    run,
)
from tests.intelligence.test_learning_runtime_endpoints import (
    runtime as runtime_fixture,
)
from tests.signal_events.fakes import MemorySignalIngestionRepository


@pytest.fixture(name="runtime")
def consent_runtime(monkeypatch):
    yield from runtime_fixture.__wrapped__(monkeypatch)


def configure(runtime, state):
    app = runtime.client.app
    app.dependency_overrides.pop(require_learning_consent_if_student)
    app.dependency_overrides[get_scaffold_fading_service] = lambda: SimpleNamespace()
    repository = MemoryConsentRepository()
    if state != "missing":
        repository.records[(runtime.ids["student"], ConsentType.DATA_PROCESSING)] = (
            ConsentRecordView(
                id=uuid4(),
                student_id=runtime.ids["student"],
                consent_type=ConsentType.DATA_PROCESSING,
                status=ConsentStatus(state),
                confirmation_source=None,
                confirmed_via=None,
                confirmed_at=datetime.now(UTC) if state == "confirmed" else None,
            )
        )
    app.state.consent_service = ConsentService(
        repository=repository,
        token_service=FixedConsentTokenService(),
        public_base_url="https://example.test",
    )
    signals = MemorySignalIngestionRepository()
    app.state.signal_ingestion_service = SignalIngestionService(signals)
    ask = FakeAskNevoService()
    app.state.ask_nevo_service = ask
    for router in (signals_router, ask_router, consent_router):
        app.include_router(router)
    return repository, signals, ask


def requests(runtime, sitting):
    lesson = f"/api/v1/lessons/{runtime.ids['lesson']}"
    return [
        ("POST", lesson + "/session", None),
        (
            "POST",
            lesson + "/attempts",
            {
                "sessionId": sitting,
                "questionId": "q1",
                "segmentId": str(runtime.ids["segment"]),
                "answer": 5,
                "responseTimeMs": 3000,
            },
        ),
        ("PUT", lesson + "/progress", {"sessionId": sitting, "status": "in_progress"}),
        (
            "POST",
            "/api/signals/",
            {
                "session": {
                    "sessionId": sitting,
                    "startedAt": (datetime.now(UTC) - timedelta(seconds=30)).isoformat(),
                },
                "events": [
                    {"sessionId": sitting, "eventType": "scroll", "eventData": {"depthRatio": 0.5}}
                ],
            },
        ),
        (
            "POST",
            "/api/v1/ask-nevo/",
            {
                "role": "student",
                "currentPage": "home",
                "contextIds": {},
                "question": "What can I learn today?",
            },
        ),
        ("GET", lesson, None),
        ("GET", f"/api/content/lessons/{runtime.ids['lesson']}", None),
        ("GET", lesson + "/offline-package", None),
        ("GET", lesson + "/offline-package.json", None),
        ("POST", lesson + "/download", None),
        (
            "POST",
            "/api/intelligence/guided-questions/answer",
            {
                "studentId": str(runtime.ids["student"]),
                "promptId": "prompt-1",
                "responseLength": 10,
            },
        ),
        (
            "POST",
            "/api/intelligence/scaffolds/attempt",
            {
                "studentId": str(runtime.ids["student"]),
                "conceptId": str(runtime.ids["concept"]),
                "problemId": "problem-1",
                "answerAttemptId": str(uuid4()),
            },
        ),
        ("POST", f"/api/v1/ask-nevo/{uuid4()}/helpfulness", {"helpful": True}),
    ]


@pytest.mark.parametrize(
    "state,code",
    [
        ("missing", "consent_required"),
        ("pending", "consent_pending"),
        ("not_sent", "consent_required"),
        ("withdrawn", "consent_withdrawn"),
    ],
)
def test_unconfirmed_consent_blocks_processing_before_any_learning_write(runtime, state, code):
    _, signals, ask = configure(runtime, state)
    gate = runtime.client.get("/api/v1/students/me/consent-gate")
    assert gate.status_code == 200, gate.text
    assert gate.json()["blocked"] is True and gate.json()["granted"] is False
    for method, url, payload in requests(runtime, str(uuid4())):
        response = runtime.client.request(method, url, json=payload)
        assert response.status_code == 403, (url, response.text)
        assert response.json()["detail"]["code"] == code, (url, response.text)
    assert ask.requests == [] and signals.batches == []

    async def verify():
        async with runtime.sessions() as session:
            for model in (LessonSession, LessonQuestionAttempt, LessonProgress):
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.student_id == runtime.ids["student"])
                    )
                    == 0
                )

    run(verify())


def test_confirmed_consent_allows_real_answers_progress_signals_and_ask(runtime):
    repository, signals, ask = configure(runtime, "confirmed")
    lesson = f"/api/v1/lessons/{runtime.ids['lesson']}"
    started = runtime.client.post(lesson + "/session")
    assert started.status_code == 201, started.text
    sitting = started.json()["sessionId"]
    for method, url, payload in requests(runtime, sitting)[1:5]:
        response = runtime.client.request(method, url, json=payload)
        assert response.status_code in {200, 201, 202}, (url, response.text)
    assert len(ask.requests) == 1 and len(signals.batches) == 1

    # A later withdrawal blocks the same signed-in session, without a browser refresh.
    from dataclasses import replace

    key = (runtime.ids["student"], ConsentType.DATA_PROCESSING)
    repository.records[key] = replace(repository.records[key], status=ConsentStatus.WITHDRAWN)
    response = runtime.client.put(
        lesson + "/progress", json={"sessionId": sitting, "status": "in_progress"}
    )
    assert response.status_code == 403 and response.json()["detail"]["code"] == "consent_withdrawn"


@pytest.mark.parametrize("failure", ["missing_service", "failed_lookup"])
def test_unavailable_consent_stops_all_processing(runtime, failure):
    repository, signals, ask = configure(runtime, "confirmed")
    if failure == "missing_service":
        del runtime.client.app.state.consent_service
    else:
        repository.consent_status = AsyncMock(side_effect=RuntimeError("database unavailable"))
    for method, url, payload in requests(runtime, str(uuid4())):
        response = runtime.client.request(method, url, json=payload)
        assert response.status_code == 503, (url, response.text)
        assert response.json()["detail"]["code"] == "consent_service_unavailable"
    assert signals.batches == [] and ask.requests == []


def test_queued_work_waits_for_confirmation_then_resumes(runtime):
    profiles = SimpleNamespace(update_after_lesson=AsyncMock())
    flags = SimpleNamespace(evaluate_student=AsyncMock())
    worker = PostLessonProcessingWorker(
        sessions=runtime.sessions, profile_service=profiles, flag_service=flags
    )
    session_id = uuid4()

    async def exercise():
        await worker.enqueue(session_id=session_id, student_id=runtime.ids["student"])
        assert await worker.process_next() is True
        profiles.update_after_lesson.assert_not_awaited()
        flags.evaluate_student.assert_not_awaited()
        async with runtime.sessions.begin() as session:
            job = await session.get(PostLessonProcessing, session_id)
            assert job.status == "consent_blocked" and job.attempt_count == 0
            assert job.last_error == "consent_required"
            reviewer = uuid4()
            session.add(
                User(
                    id=reviewer,
                    school_id=runtime.ids["school"],
                    role="senco_admin",
                    first_name="Reviewer",
                    auth_method="email_password",
                    status="active",
                )
            )
            await session.flush()
            session.add(
                ConsentRecord(
                    subject_user_id=runtime.ids["student"],
                    consent_type="data_processing",
                    status="confirmed",
                    confirmed_by_admin_id=reviewer,
                    confirmation_source="school",
                    confirmed_via="written",
                    confirmed_at=datetime.now(UTC),
                    parent_name_on_form="Test Guardian",
                    signed_on=datetime.now(UTC).date(),
                    notice_version="test",
                )
            )
            job.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        assert await worker.process_next() is True
        profiles.update_after_lesson.assert_awaited_once()
        flags.evaluate_student.assert_awaited_once()
        async with runtime.sessions() as session:
            job = await session.get(PostLessonProcessing, session_id)
            assert job.status == "completed"

    run(exercise())
