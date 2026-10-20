"""Real SQL and HTTP tests, restricted to an explicitly disposable local database."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nevo.api.auth import authenticated_principal
from nevo.api.consent import require_learning_consent_if_student
from nevo.api.frontend_unblockers import router as product_router
from nevo.api.insights import router as insights_router
from nevo.api.intelligence import router as intelligence_router
from nevo.api.learning_readiness import router as readiness_router
from nevo.api.probe import router as probe_router
from nevo.api.product_learning import router as learning_router
from nevo.api.student_entry import router as entry_router
from nevo.auth.entities import AuthPrincipal
from nevo.db.models.account import School, User
from nevo.db.models.content import ContentParseRun, Lesson, LessonSegment
from nevo.db.models.frontend_support import Concept, LessonAssignment
from nevo.db.models.mastery import (
    StudentConceptMastery,
    StudentConceptScaffoldState,
    StudentConceptScheduling,
)
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.intelligence.learning_runtime import ONBOARDING_MODULES
from nevo.intelligence.wiring import (
    build_accommodation_inference_service,
    build_adaptation_engine_service,
)

URL = os.getenv("NEVO_RUNTIME_TEST_DATABASE_URL", "")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture
def runtime(monkeypatch):
    parsed = make_url(URL)
    assert parsed.host in {"127.0.0.1", "localhost"}
    assert parsed.database == "nevo_adaptation_tests"
    engine = create_async_engine(URL, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    ids = {
        name: uuid4()
        for name in ("school", "teacher", "student", "lesson", "segment", "concept", "parse")
    }

    async def seed():
        async with sessions.begin() as session:
            session.add(
                School(
                    id=ids["school"],
                    name="Runtime test school",
                    school_code=uuid4().hex[:8],
                    school_url_slug=uuid4().hex,
                    auth_method="email_password",
                )
            )
            await session.flush()
            session.add_all(
                [
                    User(
                        id=ids["teacher"],
                        school_id=ids["school"],
                        role="teacher",
                        auth_method="email_password",
                        first_name="Teacher",
                        status="active",
                    ),
                    User(
                        id=ids["student"],
                        school_id=ids["school"],
                        role="student",
                        auth_method="pin",
                        first_name="Learner",
                        status="active",
                        baseline_profile={
                            "completed_modules": list(ONBOARDING_MODULES),
                            "subject_placements": {"maths": 0.6},
                            "comprehension_accuracy": 0.8,
                            "response_time_ms": 2000,
                        },
                        engine_config={"version": 1, "support": {"initialScaffoldLevel": "strong"}},
                    ),
                ]
            )
            await session.flush()
            session.add(
                Lesson(
                    id=ids["lesson"],
                    school_id=ids["school"],
                    created_by_user_id=ids["teacher"],
                    title="Fractions",
                    subject="Maths",
                    source_type="text",
                    status="completed",
                    segment_count=1,
                )
            )
            await session.flush()
            session.add(
                ContentParseRun(
                    id=ids["parse"],
                    lesson_id=ids["lesson"],
                    requested_by_user_id=ids["teacher"],
                    source_type="text",
                    status="completed",
                )
            )
            session.add(
                Concept(
                    id=ids["concept"],
                    school_id=ids["school"],
                    lesson_id=ids["lesson"],
                    name="Fifths",
                    subject="Maths",
                    curriculum_position=0.5,
                )
            )
            await session.flush()
            session.add(
                LessonSegment(
                    id=ids["segment"],
                    lesson_id=ids["lesson"],
                    parse_run_id=ids["parse"],
                    segment_key="fifths",
                    concept_id=ids["concept"],
                    content_type="explanatory_text",
                    sequence_order=1,
                    title="Fifths",
                    body="A whole divided into five equal parts has five fifths.",
                    available_modalities=["text"],
                    approved_at=datetime.now(UTC),
                    depth_variants={
                        "simplified": {"body": "Five equal parts make a whole."},
                        "expanded": {
                            "body": "Five equal parts make one whole. Each part is one fifth."
                        },
                    },
                    calculation_variant={
                        "conceptId": str(ids["concept"]),
                        "fullEquation": "5 fifths = 1 whole",
                        "expression": "5 fifths",
                        "answer": 5,
                        "completionStatement": "You have built the whole.",
                        "steps": [
                            {
                                "stepId": "step-1",
                                "stepNumber": 1,
                                "prompt": "How many equal parts make the whole?",
                                "hint": "Count the equal parts.",
                                "answer": 5,
                                "expectedInput": "numeric",
                                "confirmationText": "That makes a whole.",
                                "visualUpdate": "Show the whole.",
                                "equationState": "5 fifths = 1 whole",
                                "input": "number",
                                "targets": [],
                                "assembles": "5 fifths = 1 whole",
                            }
                        ],
                    },
                    comprehension_checkpoints=[
                        {
                            "id": "q1",
                            "prompt": "How many fifths make one whole?",
                            "answerType": "numeric",
                            "answerKey": 5,
                            "conceptId": str(ids["concept"]),
                        }
                    ],
                )
            )
            session.add(
                LessonAssignment(
                    lesson_id=ids["lesson"], student_id=ids["student"], teacher_id=ids["teacher"]
                )
            )

    run(seed())
    app = FastAPI()
    from nevo.api.ai_gateway import get_ai_gateway

    app.dependency_overrides[get_ai_gateway] = lambda: SimpleNamespace(check_content=AsyncMock())
    app.state.db_sessions = sessions
    from nevo.auth.config import AuthSettings
    from nevo.auth.wiring import build_auth_service, build_credential_hasher

    settings = AuthSettings(
        _env_file=None,
        auth_password_pepper="password-test-" * 4,
        auth_pin_pepper="pin-test-" * 5,
        auth_session_pepper="session-test-" * 4,
    )
    hasher = build_credential_hasher(settings)
    app.state.auth_service = build_auth_service(sessions, settings, credential_hasher=hasher)
    monkeypatch.setattr("nevo.api.product_auth.credential_hasher", lambda: hasher)
    app.state.adaptation_engine_service = build_adaptation_engine_service(sessions, object())
    app.state.accommodation_inference_service = build_accommodation_inference_service(sessions)
    principal = AuthPrincipal(user_id=ids["student"], role="student", session_id=uuid4())
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.dependency_overrides[require_learning_consent_if_student] = lambda: None
    for router in (
        learning_router,
        intelligence_router,
        readiness_router,
        insights_router,
        entry_router,
        probe_router,
        product_router,
    ):
        app.include_router(router)
    fixture = SimpleNamespace(client=TestClient(app), sessions=sessions, ids=ids)
    yield fixture
    run(engine.dispose())


def start(runtime):
    response = runtime.client.post(f"/api/v1/lessons/{runtime.ids['lesson']}/session")
    assert response.status_code == 201, response.text
    return response.json()["sessionId"]


def answer(runtime, session_id, value, response_time=3000, attempt_id=None):
    return runtime.client.post(
        f"/api/v1/lessons/{runtime.ids['lesson']}/attempts",
        json={
            "sessionId": session_id,
            "segmentId": str(runtime.ids["segment"]),
            "questionId": "q1",
            "answer": value,
            "responseTimeMs": response_time,
            "clientAttemptId": str(attempt_id or uuid4()),
        },
    )


def test_missing_onboarding_blocks_session_and_reports_modules(runtime):
    async def change():
        async with runtime.sessions.begin() as session:
            user = await session.get(User, runtime.ids["student"])
            user.baseline_profile = {}

    run(change())
    response = runtime.client.post(f"/api/v1/lessons/{runtime.ids['lesson']}/session")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "onboarding_required"
    status = runtime.client.get("/api/v1/students/me/onboarding")
    assert status.status_code == 200
    assert status.json()["nextModule"] == "grid_span"


def test_answers_update_mastery_and_schedule_once_with_retries(runtime):
    sitting = start(runtime)
    key = uuid4()
    assert answer(runtime, sitting, 5, attempt_id=key).status_code == 201
    assert answer(runtime, sitting, 5, attempt_id=key).status_code == 201
    for _ in range(3):
        response = answer(runtime, sitting, 5)
        assert response.status_code == 201, response.text

    async def add_questions():
        async with runtime.sessions.begin() as session:
            segment = await session.get(LessonSegment, runtime.ids["segment"])
            original = segment.comprehension_checkpoints[0]
            segment.comprehension_checkpoints = [
                original,
                *[{**original, "id": key} for key in ("q2", "q3")],
            ]

    run(add_questions())
    for key in ("q2", "q3"):
        response = runtime.client.post(
            f"/api/v1/lessons/{runtime.ids['lesson']}/attempts",
            json={
                "sessionId": sitting,
                "segmentId": str(runtime.ids["segment"]),
                "questionId": key,
                "answer": 5,
                "responseTimeMs": 3000,
            },
        )
        assert response.status_code == 201, response.text

    async def inspect():
        async with runtime.sessions() as session:
            state = await session.scalar(
                select(StudentConceptMastery).where(
                    StudentConceptMastery.student_id == runtime.ids["student"]
                )
            )
            schedules = list(
                await session.scalars(
                    select(StudentConceptScheduling).where(
                        StudentConceptScheduling.student_id == runtime.ids["student"]
                    )
                )
            )
            assert state.practice_count == 3
            assert state.mastery_probability_concept >= 0.7
            assert len(schedules) == 1

    run(inspect())
    response = runtime.client.get("/api/v1/students/me/next-work")
    assert response.status_code == 200 and response.json() is None


def test_warmup_recalibrates_once_without_exposing_measurements(runtime, monkeypatch):
    monkeypatch.setattr("nevo.api.frontend_unblockers._today_dimension", lambda _: "reading")
    url = f"/api/baseline/recalibrate-prompt/{runtime.ids['student']}/response"
    payload = {
        "trials": [
            {
                "dimension": "reading",
                "correct": True,
                "responseTimeMs": 30_000,
                "readingWordCount": 30,
            }
        ]
    }
    response = runtime.client.post(url, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["measurementStatus"] == "recalibrated"
    assert "baselineProfile" not in response.json()
    payload["trials"][0]["responseTimeMs"] = 10_000
    assert runtime.client.post(url, json=payload).status_code == 200

    async def inspect():
        async with runtime.sessions() as session:
            student = await session.get(User, runtime.ids["student"])
            assert student.baseline_profile["reading_wpm"] == 60
            assert student.baseline_profile["subject_placements"] == {"maths": 0.6}

    run(inspect())


def test_curriculum_mapping_reports_and_repairs_assessed_gaps(runtime):
    async def unmap():
        async with runtime.sessions.begin() as session:
            segment = await session.get(LessonSegment, runtime.ids["segment"])
            segment.concept_id = None
            segment.calculation_variant = None
            segment.comprehension_checkpoints = [
                {**question, "conceptId": None} for question in segment.comprehension_checkpoints
            ]

    run(unmap())
    teacher = AuthPrincipal(user_id=runtime.ids["teacher"], role="teacher", session_id=uuid4())
    runtime.client.app.dependency_overrides[authenticated_principal] = lambda: teacher
    response = runtime.client.get("/api/v1/curriculum/readiness")
    assert response.status_code == 200, response.text
    assert response.json()["prerequisiteReviewRequired"] is True
    assert any(row["code"] == "assessed_concept_missing" for row in response.json()["findings"])
    response = runtime.client.put(
        f"/api/v1/segments/{runtime.ids['segment']}/concept",
        json={"conceptId": str(runtime.ids["concept"])},
    )
    assert response.status_code == 200, response.text
    response = runtime.client.get("/api/v1/curriculum/readiness")
    assert not any(row["code"] == "assessed_concept_missing" for row in response.json()["findings"])


def test_offline_delivery_contains_the_same_stable_reading_anchors(runtime):
    start(runtime)
    online = runtime.client.get(f"/api/v1/lessons/{runtime.ids['lesson']}")
    offline = runtime.client.get(f"/api/v1/lessons/{runtime.ids['lesson']}/offline-package.json")
    assert online.status_code == 200, online.text
    assert offline.status_code == 200, offline.text
    assert (
        offline.json()["segments"][0]["readingChunks"]
        == online.json()["segments"][0]["readingChunks"]
    )
    assert (
        offline.json()["segments"][0]["readingGroups"]
        == online.json()["segments"][0]["readingGroups"]
    )


def test_calculation_marking_rejects_distractor_alias_in_historical_data(runtime):
    async def change():
        async with runtime.sessions.begin() as session:
            segment = await session.get(LessonSegment, runtime.ids["segment"])
            segment.calculation_variant = {
                "steps": [
                    {
                        "stepId": "choice",
                        "prompt": "Choose four",
                        "answer": "a",
                        "acceptedAnswers": ["b", "4"],
                        "options": [{"value": "a", "label": "4"}, {"value": "b", "label": "7"}],
                    }
                ],
                "conceptId": str(runtime.ids["concept"]),
                "answer": 4,
            }

    run(change())
    sitting = start(runtime)
    response = runtime.client.post(
        f"/api/v1/lessons/{runtime.ids['lesson']}/attempts",
        json={
            "sessionId": sitting,
            "segmentId": str(runtime.ids["segment"]),
            "questionId": "choice",
            "source": "calculation",
            "answer": "b",
            "responseTimeMs": 3000,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["correct"] is False


def test_completed_review_updates_existing_schedule_once(runtime):
    from nevo.api.scheduler import router as scheduler_router
    from nevo.db.models.review_evidence import ConceptReviewEvidence
    from nevo.scheduler.wiring import build_scheduler_service

    runtime.client.app.include_router(scheduler_router)
    runtime.client.app.state.scheduler_service = build_scheduler_service(runtime.sessions)
    sitting = start(runtime)
    assert answer(runtime, sitting, 5).status_code == 201

    async def old_schedule():
        async with runtime.sessions.begin() as session:
            existing = await session.scalar(
                select(StudentConceptScheduling).where(
                    StudentConceptScheduling.student_id == runtime.ids["student"],
                    StudentConceptScheduling.concept_id == runtime.ids["concept"],
                )
            )
            if existing is None:
                existing = StudentConceptScheduling(
                    student_id=runtime.ids["student"], concept_id=runtime.ids["concept"]
                )
                session.add(existing)
            existing.stability, existing.difficulty, existing.review_count = 10, 5, 1
            existing.last_review = datetime.now(UTC) - timedelta(days=2)
            existing.next_review_due = datetime.now(UTC) - timedelta(hours=1)

    run(old_schedule())
    payload = {
        "sessionId": sitting,
        "status": "completed",
        "segmentPosition": 0,
        "modulePosition": 0,
    }
    for _ in range(2):
        response = runtime.client.put(
            f"/api/v1/lessons/{runtime.ids['lesson']}/progress", json=payload
        )
        assert response.status_code == 200, response.text
    for _ in range(2):
        response = runtime.client.post(
            "/api/scheduler/record-review",
            json={
                "studentId": str(runtime.ids["student"]),
                "conceptId": str(runtime.ids["concept"]),
                "sessionId": sitting,
                "outcome": "not_recalled",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["schedule"]["stability"] is None

    async def inspect():
        async with runtime.sessions() as session:
            current = await session.scalar(
                select(StudentConceptScheduling).where(
                    StudentConceptScheduling.student_id == runtime.ids["student"],
                )
            )
            assert current.review_count == 2
            assert current.stability > 10
            evidence = list(
                await session.scalars(
                    select(ConceptReviewEvidence).where(
                        ConceptReviewEvidence.student_id == runtime.ids["student"],
                    )
                )
            )
            assert len(evidence) == 1
            assert evidence[0].outcome == "first_time"

    run(inspect())


def test_review_uses_attempt_numbers_when_save_timestamps_are_reversed(runtime):
    from uuid import UUID

    from nevo.db.models.product import LessonQuestionAttempt
    from nevo.db.models.review_evidence import ConceptReviewEvidence

    sitting = start(runtime)
    assert answer(runtime, sitting, 4).status_code == 201
    assert answer(runtime, sitting, 5).status_code == 201

    async def reverse_timestamps():
        async with runtime.sessions.begin() as session:
            rows = list(
                await session.scalars(
                    select(LessonQuestionAttempt)
                    .where(LessonQuestionAttempt.session_id == UUID(sitting))
                    .order_by(LessonQuestionAttempt.attempt_number)
                )
            )
            rows[0].submitted_at = rows[1].submitted_at + timedelta(seconds=1)

    run(reverse_timestamps())
    response = runtime.client.put(
        f"/api/v1/lessons/{runtime.ids['lesson']}/progress",
        json={
            "sessionId": sitting,
            "status": "completed",
            "segmentPosition": 0,
            "modulePosition": 0,
        },
    )
    assert response.status_code == 200, response.text

    async def inspect():
        async with runtime.sessions() as session:
            evidence = await session.scalar(
                select(ConceptReviewEvidence).where(
                    ConceptReviewEvidence.session_id == UUID(sitting)
                )
            )
            assert evidence.outcome == "second_attempt"

    run(inspect())


def test_scaffold_compatibility_receipt_cannot_apply_a_second_update(runtime):
    from nevo.intelligence.wiring import build_scaffold_fading_service

    runtime.client.app.state.scaffold_fading_service = build_scaffold_fading_service(
        runtime.sessions
    )
    sitting = start(runtime)
    attempt = answer(runtime, sitting, 5)
    assert attempt.status_code == 201, attempt.text
    payload = {
        "studentId": str(runtime.ids["student"]),
        "conceptId": str(runtime.ids["concept"]),
        "problemId": "invented",
        "answerAttemptId": attempt.json()["id"],
        "responseCorrect": True,
        "scaffoldIntensity": "independent",
    }
    for _ in range(3):
        response = runtime.client.post("/api/intelligence/scaffolds/attempt", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["nextIntensity"] == "full_support"
        assert response.json()["levelChanged"] is False

    async def inspect():
        async with runtime.sessions() as session:
            state = await session.scalar(
                select(StudentConceptScaffoldState).where(
                    StudentConceptScaffoldState.student_id == runtime.ids["student"],
                )
            )
            assert state.consecutive_correct == 1

    run(inspect())


def test_fast_taps_cannot_increase_mastery(runtime):
    sitting = start(runtime)
    for _ in range(2):
        response = answer(runtime, sitting, 5, response_time=1)
        assert response.status_code == 201, response.text

    async def inspect():
        async with runtime.sessions() as session:
            state = await session.scalar(
                select(StudentConceptMastery).where(
                    StudentConceptMastery.student_id == runtime.ids["student"]
                )
            )
            assert state.mastery_probability_concept == 0.6
            assert state.practice_count == 0

    run(inspect())


def test_numeric_equivalence_is_saved_and_survives_read(runtime):
    async def change_question():
        async with runtime.sessions.begin() as session:
            segment = await session.get(LessonSegment, runtime.ids["segment"])
            questions = list(segment.comprehension_checkpoints)
            questions[0] = {
                **questions[0],
                "answerKey": "1/2",
                "answerType": "numeric",
                "acceptedAnswers": ["one half"],
            }
            segment.comprehension_checkpoints = questions

    run(change_question())
    sitting = start(runtime)
    result = answer(runtime, sitting, "0.5")
    assert result.status_code == 201, result.text
    assert result.json()["correct"] is True
    result = answer(runtime, sitting, "one half")
    assert result.status_code == 201 and result.json()["correct"] is True


def test_client_scores_cannot_manufacture_an_adaptation(runtime):
    sitting = start(runtime)
    response = adapt(
        runtime,
        sitting,
        comprehensionScore=0,
        sessionAverageComprehension=100,
        engagementScore=0,
        engagementBaseline=1,
        engagementBelowBaselineSeconds=999,
        consecutiveErrors=9,
        accuracyBelowBaseline=True,
        responseTimeBelowBaseline=True,
    )
    assert response.status_code == 200, response.text
    assert response.json()["proactiveAdjustment"] is None
    assert response.json()["modalitySuggestion"] is None


def test_timed_reading_then_warmup_preserves_the_rest_of_the_baseline(runtime):
    response = runtime.client.post(
        "/api/baseline/trials",
        json={
            "sessionId": "reading-run",
            "trials": [
                {
                    "dimension": "reading",
                    "correct": True,
                    "responseTimeMs": 30000,
                    "readingWordCount": 30,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text

    async def saved_profile():
        async with runtime.sessions() as session:
            return (await session.get(User, runtime.ids["student"])).baseline_profile

    assert response.json()["baselineProfile"] == {}
    profile = run(saved_profile())
    assert profile["reading_wpm"] == 60
    assert profile["reading_wpm_source"] == "measured"
    later = runtime.client.post(
        "/api/baseline/trials",
        json={
            "sessionId": "warmup-run",
            "trials": [{"dimension": "ps", "correct": True, "responseTimeMs": 1000}],
        },
    )
    assert later.status_code == 200, later.text
    saved = run(saved_profile())
    assert saved["reading_wpm"] == 60
    assert saved["comprehension_accuracy"] == profile["comprehension_accuracy"]
    assert saved["subject_placements"] == profile["subject_placements"]


def test_real_errors_offer_help_without_client_computed_metrics(runtime):
    sitting = start(runtime)
    for _ in range(2):
        assert answer(runtime, sitting, 0).status_code == 201
    response = adapt(runtime, sitting)
    assert response.status_code == 200, response.text
    assert response.json()["proactiveAdjustment"]["action"] == "offer_hint"


def test_lesson_completion_creates_first_review_before_mastery(runtime):
    sitting = start(runtime)
    assert answer(runtime, sitting, 5).status_code == 201
    response = runtime.client.put(
        f"/api/v1/lessons/{runtime.ids['lesson']}/progress",
        json={
            "sessionId": sitting,
            "status": "completed",
            "modulePosition": 0,
            "segmentPosition": 0,
        },
    )
    assert response.status_code == 200, response.text

    async def inspect():
        async with runtime.sessions() as session:
            rows = list(
                await session.scalars(
                    select(StudentConceptScheduling).where(
                        StudentConceptScheduling.student_id == runtime.ids["student"]
                    )
                )
            )
            assert len(rows) == 1
            assert rows[0].next_review_due > rows[0].last_review

    run(inspect())


def adapt(runtime, sitting, **signals):
    return runtime.client.post(
        "/api/intelligence/adapt",
        json={
            "lessonId": str(runtime.ids["lesson"]),
            "sessionId": sitting,
            "segments": [
                {
                    "id": str(runtime.ids["segment"]),
                    "segmentType": "explanation",
                    "availableModalities": ["text"],
                }
            ],
            "signals": {
                "currentSegmentId": str(runtime.ids["segment"]),
                "currentModality": "text",
                **signals,
            },
        },
    )


def test_quiet_work_has_no_adjustment_and_actual_help_is_served(runtime):
    sitting = start(runtime)
    quiet = adapt(
        runtime,
        sitting,
        comprehensionScore=80,
        sessionAverageComprehension=80,
        engagementScore=0.7,
        engagementBaseline=0.7,
    )
    assert quiet.status_code == 200, quiet.text
    assert quiet.json()["proactiveAdjustment"] is None
    for _ in range(2):
        assert answer(runtime, sitting, 0).status_code == 201
    helped = adapt(
        runtime,
        sitting,
        comprehensionScore=30,
        sessionAverageComprehension=80,
        accuracyBelowBaseline=True,
        engagementBelowBaselineSeconds=190,
    )
    assert helped.status_code == 200, helped.text
    assert helped.json()["proactiveAdjustment"]["action"] == "offer_hint"
    assert helped.json()["proactiveAdjustment"]["hint"] == "Count the equal parts."
    assert answer(runtime, sitting, 3).status_code == 201
    panel = adapt(
        runtime,
        sitting,
        comprehensionScore=30,
        sessionAverageComprehension=80,
        accuracyBelowBaseline=True,
        engagementBelowBaselineSeconds=190,
    )
    assert panel.status_code == 200, panel.text
    assert panel.json()["proactiveAdjustment"]["action"] == "show_socratic_panel"


def test_session_delivery_is_frozen_after_account_config_changes(runtime):
    sitting = start(runtime)
    before = runtime.client.get(f"/api/session/state/{runtime.ids['student']}?sessionId={sitting}")
    assert before.status_code == 200, before.text

    async def change():
        async with runtime.sessions.begin() as session:
            user = await session.get(User, runtime.ids["student"])
            user.engine_config = {"reading": {"targetWordsPerMinute": 35}}

    run(change())
    after = runtime.client.get(f"/api/session/state/{runtime.ids['student']}?sessionId={sitting}")
    assert after.status_code == 200, after.text
    assert after.json()["engineConfig"] == before.json()["engineConfig"]


def test_prerequisite_refuses_session(runtime):
    async def change():
        async with runtime.sessions.begin() as session:
            prerequisite = Concept(
                school_id=runtime.ids["school"], name="Equal groups", subject="Maths"
            )
            session.add(prerequisite)
            await session.flush()
            target = await session.get(Concept, runtime.ids["concept"])
            target.prerequisite_ids = [str(prerequisite.id)]

    run(change())
    response = runtime.client.post(f"/api/v1/lessons/{runtime.ids['lesson']}/session")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "prerequisite_work_required"


def test_cooldown_comes_from_server_even_with_default_mode(runtime):
    sitting = start(runtime)
    for _ in range(3):
        assert answer(runtime, sitting, 4).status_code == 201

    async def change():
        async with runtime.sessions.begin() as session:
            session.add(
                SignalEvent(
                    student_id=runtime.ids["student"],
                    session_id=sitting,
                    event_type="simplify_trigger",
                    timestamp=datetime.now(UTC),
                    event_data={"segmentId": str(runtime.ids["segment"])},
                )
            )

    run(change())
    response = adapt(
        runtime,
        sitting,
        comprehensionScore=30,
        sessionAverageComprehension=80,
        accuracyBelowBaseline=True,
        engagementBelowBaselineSeconds=190,
    )
    assert response.status_code == 200, response.text
    assert response.json()["proactiveAdjustment"] is None
    assert response.json()["suppressedAttempt"]["reason"] == "adaptation_cooldown"


def test_five_distinct_lessons_activate_reading_on_next_sitting(runtime):
    async def history():
        async with runtime.sessions.begin() as session:
            for index in range(5):
                lesson = Lesson(
                    school_id=runtime.ids["school"],
                    created_by_user_id=runtime.ids["teacher"],
                    title=f"Reading {index}",
                    source_type="text",
                )
                session.add(lesson)
                await session.flush()
                sitting = LessonSession(
                    id=uuid4(),
                    student_id=runtime.ids["student"],
                    lesson_id=lesson.id,
                    started_at=datetime.now(UTC) - timedelta(days=index + 1),
                    completion_status="completed",
                )
                session.add(sitting)
                await session.flush()
                session.add(
                    SignalEvent(
                        student_id=runtime.ids["student"],
                        session_id=sitting.id,
                        event_type="time_on_segment",
                        timestamp=sitting.started_at,
                        event_data={
                            "textHeavy": True,
                            "readingLatencyRatio": 2,
                            "backwardScrollCount": 3,
                            "longWordPause": True,
                        },
                    )
                )

    run(history())
    sitting = start(runtime)
    response = runtime.client.get(
        f"/api/session/state/{runtime.ids['student']}?sessionId={sitting}"
    )
    assert response.status_code == 200, response.text
    assert response.json()["accommodations"] == ["reading"]
    assert response.json()["engineConfig"]["reading"]["fontScale"] == 1.15
    current = runtime.client.get(f"/api/intelligence/accommodations/{runtime.ids['student']}")
    assert current.status_code == 200, current.text
    assert current.json()["activeAccommodations"] == ["reading"]
    assert current.json()["source"] == "session_delivery_snapshot"

    async def inspect():
        async with runtime.sessions() as session:
            student = await session.get(User, runtime.ids["student"])
            assert "accommodations" not in student.engine_config

    run(inspect())


def test_repeated_attempts_are_not_three_separate_scaffold_problems(runtime):
    sitting = start(runtime)
    for _ in range(4):
        assert answer(runtime, sitting, 5).status_code == 201

    async def inspect():
        async with runtime.sessions() as session:
            state = await session.scalar(
                select(StudentConceptScaffoldState).where(
                    StudentConceptScaffoldState.student_id == runtime.ids["student"]
                )
            )
            assert state.current_intensity == "full_support"
            assert state.consecutive_correct == 1

    run(inspect())


def test_strong_and_weak_placement_select_different_assigned_concepts(runtime):
    async def setup():
        async with runtime.sessions.begin() as session:
            target = await session.get(Concept, runtime.ids["concept"])
            target.curriculum_position = 0.1
            advanced = Concept(
                school_id=runtime.ids["school"],
                lesson_id=runtime.ids["lesson"],
                name="Adding fifths",
                subject="Maths",
                curriculum_position=0.9,
            )
            session.add(advanced)
            await session.flush()
            session.add(
                LessonSegment(
                    lesson_id=runtime.ids["lesson"],
                    parse_run_id=runtime.ids["parse"],
                    segment_key="adding-fifths",
                    concept_id=advanced.id,
                    content_type="explanatory_text",
                    sequence_order=2,
                    title="Adding fifths",
                    body="Combine equal fifths to add them.",
                    available_modalities=["text"],
                )
            )
            user = await session.get(User, runtime.ids["student"])
            user.baseline_profile = {**user.baseline_profile, "subject_placements": {"maths": 0.1}}

    run(setup())
    weak = runtime.client.get("/api/v1/students/me/next-work?subject=Maths")
    assert weak.status_code == 200, weak.text
    assert weak.json()["conceptName"] == "Fifths"

    async def strong():
        async with runtime.sessions.begin() as session:
            user = await session.get(User, runtime.ids["student"])
            user.baseline_profile = {**user.baseline_profile, "subject_placements": {"maths": 0.9}}

    run(strong())
    response = runtime.client.get("/api/v1/students/me/next-work?subject=Maths")
    assert response.status_code == 200, response.text
    assert response.json()["conceptName"] == "Adding fifths"
    assert response.json()["segmentPosition"] == 1


@pytest.mark.parametrize("problem", ["cancelled", "future", "unreviewed", "unmapped", "processing"])
def test_next_work_never_returns_undeliverable_content(runtime, problem):
    async def prepare():
        async with runtime.sessions.begin() as session:
            segment = await session.get(LessonSegment, runtime.ids["segment"])
            assignment = await session.scalar(
                select(LessonAssignment).where(
                    LessonAssignment.student_id == runtime.ids["student"]
                )
            )
            if problem == "cancelled":
                assignment.status = "cancelled"
            elif problem == "future":
                assignment.available_from = datetime.now(UTC) + timedelta(days=1)
            elif problem == "unreviewed":
                segment.needs_review, segment.approved_at = True, None
            elif problem == "unmapped":
                segment.concept_id = None
                segment.calculation_variant = None
                segment.comprehension_checkpoints = []
            else:
                lesson = await session.get(Lesson, runtime.ids["lesson"])
                lesson.status = "processing"

    run(prepare())
    response = runtime.client.get("/api/v1/students/me/next-work")
    assert response.status_code == 200, response.text
    assert response.json() is None


def test_next_work_uses_explicit_question_mapping_when_segment_mapping_is_missing(runtime):
    async def prepare():
        async with runtime.sessions.begin() as session:
            segment = await session.get(LessonSegment, runtime.ids["segment"])
            segment.concept_id = None
            segment.calculation_variant = None

    run(prepare())
    response = runtime.client.get("/api/v1/students/me/next-work")
    assert response.status_code == 200, response.text
    assert response.json()["segmentId"] == str(runtime.ids["segment"])


def test_next_work_uses_assigned_section_not_the_concepts_unassigned_origin(runtime):
    async def prepare():
        async with runtime.sessions.begin() as session:
            origin = Lesson(
                school_id=runtime.ids["school"],
                created_by_user_id=runtime.ids["teacher"],
                title="Unassigned origin",
                subject="Maths",
                source_type="text",
                status="completed",
            )
            session.add(origin)
            await session.flush()
            concept = await session.get(Concept, runtime.ids["concept"])
            concept.lesson_id = origin.id
            segment = await session.get(LessonSegment, runtime.ids["segment"])
            segment.concept_id = None

    run(prepare())
    response = runtime.client.get("/api/v1/students/me/next-work")
    assert response.status_code == 200, response.text
    assert response.json()["lessonId"] == str(runtime.ids["lesson"])
    assert response.json()["segmentId"] == str(runtime.ids["segment"])


def test_baseline_unmarked_trials_are_not_stored_as_failed_measurements(runtime):
    response = runtime.client.post(
        "/api/baseline/trials",
        json={
            "sessionId": "unmarked",
            "trials": [
                {"dimension": "reading", "responseTimeMs": 3000},
            ],
        },
    )
    assert response.status_code == 200, response.text

    async def inspect():
        async with runtime.sessions() as session:
            student = await session.get(User, runtime.ids["student"])
            assert "reading" not in (student.baseline_profile.get("measurements") or {})

    run(inspect())


def test_session_keeps_existing_delivery_support_without_new_accommodation_evidence(runtime):
    async def prepare():
        async with runtime.sessions.begin() as session:
            user = await session.get(User, runtime.ids["student"])
            user.engine_config = {
                "support": {
                    "shorterTextBlocks": True,
                    "pauseBetweenSegments": True,
                    "numberProblemsStepByStep": True,
                }
            }

    run(prepare())
    response = runtime.client.post(f"/api/v1/lessons/{runtime.ids['lesson']}/session")
    assert response.status_code == 201, response.text
    response = runtime.client.get(
        f"/api/session/state/{runtime.ids['student']}?sessionId={response.json()['sessionId']}"
    )
    assert response.status_code == 200, response.text
    support = response.json()["engineConfig"]["support"]
    assert support["shorterTextBlocks"] is True
    assert support["pauseBetweenSegments"] is True
    assert support["numberProblemsStepByStep"] is True


def test_new_child_first_pin_four_modules_then_lesson_with_real_bearer(runtime):
    from nevo.db.models.account import Class, ConsentRecord, StudentClassEnrollment
    from nevo.db.models.probe import ProbeItem
    from nevo.db.models.subject import ClassSubject, SchoolSubject

    subject_id = uuid4()

    async def prepare():
        async with runtime.sessions.begin() as session:
            child = await session.get(User, runtime.ids["student"])
            child.baseline_profile = {}
            child.engine_config = {}
            child.admission_number = "RUNTIME/01"
            child.login_identifier = "runtime.child"
            parent = User(
                school_id=runtime.ids["school"],
                role="parent_guardian",
                auth_method="email_password",
                status="active",
            )
            session.add(parent)
            await session.flush()
            session.add(
                ConsentRecord(
                    subject_user_id=child.id,
                    consent_type="data_processing",
                    status="confirmed",
                    confirmation_source="parent",
                    confirmed_by_parent_id=parent.id,
                    confirmed_via="digital",
                    confirmed_at=datetime.now(UTC),
                )
            )
            classroom = Class(
                school_id=child.school_id,
                name="Primary 5",
                normalised_name="primary 5",
                academic_session="2026/2027",
            )
            session.add(classroom)
            session.add(
                SchoolSubject(
                    id=subject_id,
                    school_id=child.school_id,
                    name="Maths",
                    normalised_name="maths",
                    origin="school",
                    review_state="pending",
                )
            )
            await session.flush()
            session.add(StudentClassEnrollment(student_id=child.id, class_id=classroom.id))
            session.add(ClassSubject(class_id=classroom.id, school_subject_id=subject_id))
            for index in range(5):
                session.add(
                    ProbeItem(
                        school_id=child.school_id,
                        school_subject_id=subject_id,
                        question=f"Which option represents {index + 1} fifths?",
                        options=[
                            {"value": "a", "label": "Equal fifths"},
                            {"value": "b", "label": "Unequal parts"},
                        ],
                        correct_option="a",
                        difficulty=index / 5,
                        concept_id=runtime.ids["concept"],
                        lesson_id=runtime.ids["lesson"],
                    )
                )
            school = await session.get(School, child.school_id)
            return school.school_code

    school_code = run(prepare())
    lookup = runtime.client.post(
        "/api/v1/student-entry/lookup",
        json={"schoolCode": school_code, "admissionNumber": "RUNTIME/01"},
    )
    assert lookup.status_code == 200, lookup.text
    assert lookup.json()["pinState"] == "not_set"
    pin = runtime.client.post(
        "/api/v1/student-entry/pin",
        json={"schoolCode": school_code, "admissionNumber": "RUNTIME/01", "pin": "2468"},
    )
    assert pin.status_code == 200, pin.text
    runtime.client.app.dependency_overrides.pop(authenticated_principal)
    runtime.client.headers["Authorization"] = f"Bearer {pin.json()['session']['accessToken']}"
    blocked = runtime.client.post(f"/api/v1/lessons/{runtime.ids['lesson']}/session")
    assert blocked.status_code == 409, blocked.text
    baseline = runtime.client.post(
        "/api/baseline/trials",
        json={
            "sessionId": "first-baseline",
            "trials": [
                {"dimension": dimension, "correct": True, "responseTimeMs": 2500}
                for dimension in ("wmc", "ps", "attention", "reading", "ans")
            ],
        },
    )
    assert baseline.status_code == 200, baseline.text
    ready = runtime.client.get("/api/v1/students/me/onboarding")
    assert ready.status_code == 200, ready.text
    assert ready.json()["nextModule"] == "domain_probe"
    assert ready.json()["subjects"][0]["subjectId"] == str(subject_id)
    probe = runtime.client.get(f"/api/v1/probe/{subject_id}/next")
    assert probe.status_code == 200, probe.text
    while not probe.json().get("finished"):
        probe = runtime.client.post(
            f"/api/v1/probe/{subject_id}/answer",
            json={"itemId": probe.json()["itemId"], "chosenOption": "a"},
        )
        assert probe.status_code == 200, probe.text
    ready = runtime.client.get("/api/v1/students/me/onboarding")
    assert ready.json()["complete"] is True
    opened = runtime.client.post(f"/api/v1/lessons/{runtime.ids['lesson']}/session")
    assert opened.status_code == 201, opened.text


def test_three_distinct_problems_fade_and_a_miss_restores_support(runtime):
    async def questions():
        async with runtime.sessions.begin() as session:
            segment = await session.get(LessonSegment, runtime.ids["segment"])
            base = segment.comprehension_checkpoints[0]
            segment.comprehension_checkpoints = [
                {**base, "id": f"q{index}"} for index in range(1, 5)
            ]

    run(questions())
    sitting = start(runtime)
    for index in range(1, 4):
        response = runtime.client.post(
            f"/api/v1/lessons/{runtime.ids['lesson']}/attempts",
            json={
                "sessionId": sitting,
                "segmentId": str(runtime.ids["segment"]),
                "questionId": f"q{index}",
                "answer": 5,
                "responseTimeMs": 3000,
            },
        )
        assert response.status_code == 201, response.text
    response = adapt(runtime, sitting, comprehensionScore=80, sessionAverageComprehension=80)
    assert response.status_code == 200, response.text
    assert response.json()["segments"][0]["scaffolding"] == "standard"
    missed = runtime.client.post(
        f"/api/v1/lessons/{runtime.ids['lesson']}/attempts",
        json={
            "sessionId": sitting,
            "segmentId": str(runtime.ids["segment"]),
            "questionId": "q4",
            "answer": 0,
            "responseTimeMs": 3000,
        },
    )
    assert missed.status_code == 201, missed.text
    response = adapt(runtime, sitting, comprehensionScore=80, sessionAverageComprehension=80)
    assert response.json()["segments"][0]["scaffolding"] == "strong"


def test_lower_reroute_is_repeatable_and_has_real_support_directives(runtime):
    sitting = start(runtime)
    assert answer(runtime, sitting, 0).status_code == 201
    payload = {
        "sessionId": sitting,
        "status": "completed",
        "modulePosition": 0,
        "segmentPosition": 0,
    }
    first = runtime.client.put(f"/api/v1/lessons/{runtime.ids['lesson']}/progress", json=payload)
    assert first.status_code == 200, first.text
    reroute = first.json()["reroute"]
    assert reroute["deliveryState"]["engineConfig"]["support"]["initialScaffoldLevel"] == "strong"
    assert reroute["deliveryState"]["engineConfig"]["support"]["shorterTextBlocks"] is True
    again = runtime.client.put(f"/api/v1/lessons/{runtime.ids['lesson']}/progress", json=payload)
    assert again.status_code == 200, again.text
    assert again.json()["reroute"]["sessionId"] == reroute["sessionId"]
    resumed = runtime.client.post(f"/api/v1/lessons/{runtime.ids['lesson']}/session")
    assert resumed.status_code == 201, resumed.text
    assert resumed.json()["sessionId"] == reroute["sessionId"]


def test_next_day_creates_a_new_snapshot_but_keeps_the_saved_position(runtime):
    sitting = start(runtime)

    async def age():
        async with runtime.sessions.begin() as session:
            row = await session.get(LessonSession, sitting)
            row.started_at = datetime.now(UTC) - timedelta(days=1)

    run(age())
    fresh = runtime.client.post(f"/api/v1/lessons/{runtime.ids['lesson']}/session")
    assert fresh.status_code == 201, fresh.text
    assert fresh.json()["sessionId"] != sitting
    assert fresh.json()["resumed"] is False
    assert fresh.json()["segmentPosition"] == 0


def test_curriculum_write_read_and_cycle_refusal(runtime):
    principal = AuthPrincipal(user_id=runtime.ids["teacher"], role="teacher", session_id=uuid4())
    runtime.client.app.dependency_overrides[authenticated_principal] = lambda: principal
    url = f"/api/v1/concepts/{runtime.ids['concept']}/curriculum"
    written = runtime.client.put(url, json={"curriculumPosition": 0.4, "prerequisiteIds": []})
    assert written.status_code == 200, written.text
    current = runtime.client.get(url)
    assert current.status_code == 200, current.text
    assert current.json()["curriculumPosition"] == 0.4
    cycle = runtime.client.put(
        url, json={"curriculumPosition": 0.4, "prerequisiteIds": [str(runtime.ids["concept"])]}
    )
    assert cycle.status_code == 422, cycle.text
    assert cycle.json()["detail"]["code"] == "curriculum_cycle"


def test_depth_backfill_review_keeps_original_approval_and_hides_pending_text(runtime):
    original = datetime.now(UTC) - timedelta(days=1)

    async def seed_pending():
        async with runtime.sessions.begin() as session:
            row = await session.get(LessonSegment, runtime.ids["segment"])
            row.approved_at = original
            row.approved_by = runtime.ids["teacher"]
            row.depth_variants = {
                "simplified": {"body": "Count the parts.", "reviewStatus": "pending"}
            }

    run(seed_pending())
    lesson_url = f"/api/v1/lessons/{runtime.ids['lesson']}"
    child = runtime.client.get(lesson_url)
    assert child.status_code == 200, child.text
    assert child.json()["segments"][0]["depthVariants"]["simplified"] is None
    teacher = AuthPrincipal(user_id=runtime.ids["teacher"], role="teacher", session_id=uuid4())
    runtime.client.app.dependency_overrides[authenticated_principal] = lambda: teacher
    approved = runtime.client.post(f"{lesson_url}/segments/{runtime.ids['segment']}/approve")
    assert approved.status_code == 200, approved.text
    staff_read = runtime.client.get(lesson_url)
    assert staff_read.status_code == 200, staff_read.text
    rewrite = staff_read.json()["segments"][0]["depthVariants"]["simplified"]
    assert rewrite["reviewedByName"] == "Teacher"
    assert rewrite["reviewedBy"] == str(runtime.ids["teacher"])

    async def inspect():
        async with runtime.sessions() as session:
            row = await session.get(LessonSegment, runtime.ids["segment"])
            assert row.approved_at == original
            assert row.depth_variants["simplified"]["reviewStatus"] == "approved"
            assert row.depth_variants["simplified"]["reviewedBy"] == str(runtime.ids["teacher"])

    run(inspect())
