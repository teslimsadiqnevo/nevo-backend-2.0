"""Real SQL and HTTP tests, restricted to an explicitly disposable local database."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
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
                        },
                        engine_config={"version": 1},
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
                        "steps": [
                            {
                                "prompt": "How many equal parts make the whole?",
                                "hint": "Count the equal parts.",
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
            assert state.practice_count == 4
            assert state.mastery_probability_concept >= 0.7
            assert len(schedules) == 1

    run(inspect())
    response = runtime.client.get("/api/v1/students/me/next-work")
    assert response.status_code == 200 and response.json() is None


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
