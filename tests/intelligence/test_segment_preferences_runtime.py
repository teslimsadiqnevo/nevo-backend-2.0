import pytest
from sqlalchemy import select

from nevo.db.models.signal_event import SignalEvent
from tests.intelligence.test_learning_runtime_endpoints import answer, run, start
from tests.intelligence.test_learning_runtime_endpoints import runtime as runtime_fixture


@pytest.fixture(name="runtime")
def player_runtime(monkeypatch):
    yield from runtime_fixture.__wrapped__(monkeypatch)


def test_completion_queues_durable_work_once_without_an_in_process_worker(runtime):
    from nevo.db.models.product import PostLessonProcessing
    from nevo.db.models.signal_event import LessonSession

    sitting = start(runtime)
    assert answer(runtime, sitting, 5).status_code == 201
    for _ in range(2):
        response = runtime.client.put(
            f"/api/v1/lessons/{runtime.ids['lesson']}/progress",
            json={"sessionId": sitting, "status": "completed"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["intelligence"]["status"] == "pending"

    async def verify():
        from uuid import UUID

        async with runtime.sessions() as session:
            job = await session.get(PostLessonProcessing, UUID(sitting))
            lesson_session = await session.get(LessonSession, UUID(sitting))
            assert job.student_id == runtime.ids["student"]
            assert job.attempt_count == 0
            assert job.completed_at == lesson_session.ended_at

    run(verify())


def test_queue_failure_rolls_back_completion_and_retry_succeeds(runtime, monkeypatch):
    from uuid import UUID

    from nevo.api import product_learning
    from nevo.db.models.product import LessonProgress, PostLessonProcessing
    from nevo.db.models.signal_event import LessonSession

    sitting = start(runtime)
    assert answer(runtime, sitting, 5).status_code == 201
    enqueue = product_learning.enqueue_post_lesson

    async def fail_after_insert(*args, **kwargs):
        await enqueue(*args, **kwargs)
        raise RuntimeError("simulated queue transaction failure")

    url = f"/api/v1/lessons/{runtime.ids['lesson']}/progress"
    payload = {"sessionId": sitting, "status": "completed"}
    with monkeypatch.context() as patch:
        patch.setattr(product_learning, "enqueue_post_lesson", fail_after_insert)
        with pytest.raises(RuntimeError, match="simulated queue transaction failure"):
            runtime.client.put(url, json=payload)

    async def verify():
        async with runtime.sessions() as session:
            lesson_session = await session.get(LessonSession, UUID(sitting))
            assert lesson_session.ended_at is None
            assert lesson_session.completion_status == "in_progress"
            assert await session.get(PostLessonProcessing, UUID(sitting)) is None
            progress = await session.scalar(
                select(LessonProgress).where(
                    LessonProgress.student_id == runtime.ids["student"],
                    LessonProgress.lesson_id == runtime.ids["lesson"],
                )
            )
            assert progress is None or progress.status != "completed"

    run(verify())
    response = runtime.client.put(url, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["intelligence"]["status"] == "pending"


def test_choices_survive_reload_and_override_engine_without_inventing_media(runtime):
    sitting = start(runtime)
    lesson, segment = runtime.ids["lesson"], runtime.ids["segment"]
    url = f"/api/v1/lessons/{lesson}/sessions/{sitting}/segments/{segment}/preferences"
    unavailable = runtime.client.put(url, json={"modality": "audio"})
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "format_unavailable"
    saved = runtime.client.put(url, json={"modality": "interactive", "slower": True})
    assert saved.status_code == 200, saved.text
    assert saved.json()["modality"] == "interactive"
    resumed = runtime.client.post(f"/api/v1/lessons/{lesson}/session")
    assert resumed.status_code == 201, resumed.text
    assert resumed.json()["sessionId"] == sitting
    choice = resumed.json()["deliveryState"]["segmentChoices"][str(segment)]
    assert choice["modality"] == "interactive" and choice["slower"] is True
    result = runtime.client.post(
        "/api/intelligence/adapt",
        json={
            "lessonId": str(lesson),
            "sessionId": sitting,
            "mode": "lesson_load",
            "segments": [
                {"id": str(segment), "segmentType": "explanation", "availableModalities": ["text"]}
            ],
        },
    )
    assert result.status_code == 200, result.text
    adapted = result.json()["segments"][0]
    assert adapted["modality"] == "interactive" and adapted["slower"] is True
    assert adapted["recommendedFormat"] is None
    assert "audio" not in adapted["availableFormats"]
    detail = runtime.client.get(f"/api/v1/lessons/{lesson}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["segments"][0]["primaryModality"] == "interactive"
    content = runtime.client.get(f"/api/content/lessons/{lesson}")
    assert content.status_code == 200, content.text
    assert content.json()["segments"][0]["deliveryPreference"]["slower"] is True

    async def events():
        async with runtime.sessions() as session:
            rows = list(
                await session.scalars(
                    select(SignalEvent).where(
                        SignalEvent.session_id == sitting,
                        SignalEvent.event_type == "modality_manual_switch",
                    )
                )
            )
            assert len(rows) == 1
            assert rows[0].event_data["source"] == "student_control"

    run(events())


def test_completed_lesson_reopens_for_review_and_late_save_cannot_undo_it(runtime):
    sitting = start(runtime)
    assert answer(runtime, sitting, 5).status_code == 201
    url = f"/api/v1/lessons/{runtime.ids['lesson']}"
    finished = runtime.client.put(
        f"{url}/progress",
        json={"sessionId": sitting, "status": "completed", "segmentPosition": 4},
    )
    assert finished.status_code == 200, finished.text
    reopened = runtime.client.post(f"{url}/session")
    assert reopened.status_code == 201, reopened.text
    assert reopened.json()["reviewMode"] is True
    assert reopened.json()["sessionId"] == sitting
    assert reopened.json()["reviewOfSessionId"] == sitting
    assert reopened.json()["segmentPosition"] == 0
    assert reopened.json()["completedAt"]
    late = runtime.client.put(
        f"{url}/progress", json={"sessionId": sitting, "status": "in_progress"}
    )
    assert late.status_code == 200, late.text
    assert late.json()["status"] == "completed"
    assert late.json()["segmentPosition"] == 4
    dashboard = runtime.client.get("/api/v1/students/me/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    row = next(
        r for r in dashboard.json()["recentProgress"] if r["lessonId"] == str(runtime.ids["lesson"])
    )
    assert row["status"] == "completed" and row["completedAt"]


def test_handoff_uses_that_questions_own_guided_questions(runtime):
    from nevo.db.models.content import LessonSegment

    expected = ["Which particles can cross this membrane?", "Which side has more water?"]

    async def seed():
        async with runtime.sessions.begin() as session:
            row = await session.get(LessonSegment, runtime.ids["segment"])
            row.comprehension_checkpoints = [
                {**row.comprehension_checkpoints[0], "guidedQuestions": expected}
            ]

    run(seed())
    sitting = start(runtime)
    for _ in range(3):
        result = answer(runtime, sitting, 0)
        assert result.status_code == 201, result.text
    assert result.json()["handoffTo"] is None
    assert result.json()["handoffAvailableAt"]

    async def pass_grace():
        from datetime import timedelta

        from nevo.db.models.product import LessonQuestionAttempt

        async with runtime.sessions.begin() as session:
            rows = await session.scalars(
                select(LessonQuestionAttempt).where(LessonQuestionAttempt.session_id == sitting)
            )
            for row in rows:
                row.submitted_at -= timedelta(seconds=100)

    run(pass_grace())
    result = runtime.client.get(
        f"/api/v1/lessons/{runtime.ids['lesson']}/attempts?sessionId={sitting}"
    )
    assert result.status_code == 200, result.text
    assert result.json()[-1]["handoffTo"] == "socratic_panel"
    assert [row["prompt"] for row in result.json()[-1]["guidedPrompts"]] == expected


def test_adaptation_runs_after_three_distinct_unaided_successes(runtime):
    from nevo.db.models.content import LessonSegment
    from tests.intelligence.test_learning_runtime_endpoints import adapt

    async def seed():
        async with runtime.sessions.begin() as session:
            row = await session.get(LessonSegment, runtime.ids["segment"])
            question = row.comprehension_checkpoints[0]
            row.comprehension_checkpoints = [
                {**question, "id": f"success-{index}"} for index in range(3)
            ]

    run(seed())
    sitting = start(runtime)
    url = f"/api/v1/lessons/{runtime.ids['lesson']}/attempts"
    for index in range(3):
        marked = runtime.client.post(
            url,
            json={
                "sessionId": sitting,
                "segmentId": str(runtime.ids["segment"]),
                "questionId": f"success-{index}",
                "answer": 5,
                "hintCount": 0,
                "responseTimeMs": 15000,
            },
        )
        assert marked.status_code == 201, marked.text
        response = adapt(runtime, sitting)
        assert response.status_code == 200, response.text
        if index == 0:
            assert response.json()["segments"][0]["scaffolding"] == "strong"
    assert response.json()["segments"][0]["scaffolding"] == "standard"
    for _ in range(14):
        response = adapt(runtime, sitting)
        assert response.status_code == 200, response.text
        assert response.json()["segments"][0]["scaffolding"] == "standard"


def test_finishing_without_marked_answers_does_not_invent_completion(runtime):
    sitting = start(runtime)
    response = runtime.client.put(
        f"/api/v1/lessons/{runtime.ids['lesson']}/progress",
        json={"sessionId": sitting, "status": "completed"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["resultState"] == "not_attempted"
    assert response.json()["status"] == "in_progress"
    assert response.json()["intelligence"]["status"] == "not_run"


def test_no_bank_is_unestablished_and_only_module_four_reopens_when_bank_arrives(runtime):
    from uuid import uuid4

    from nevo.db.models.account import Class, StudentClassEnrollment, User
    from nevo.db.models.probe import ProbeItem
    from nevo.db.models.subject import ClassSubject, SchoolSubject

    subject_id, class_id = uuid4(), uuid4()

    async def seed():
        async with runtime.sessions.begin() as session:
            student = await session.get(User, runtime.ids["student"])
            student.baseline_profile = {
                "completed_modules": ["grid_span", "pattern_flanker", "sentence_dot"]
            }
            session.add(
                Class(
                    id=class_id, school_id=runtime.ids["school"], name="P5", academic_session="2026"
                )
            )
            session.add(
                SchoolSubject(
                    id=subject_id,
                    school_id=runtime.ids["school"],
                    name="Maths",
                    normalised_name="maths",
                    origin="school",
                    review_state="kept",
                )
            )
            await session.flush()
            session.add(StudentClassEnrollment(student_id=student.id, class_id=class_id))
            session.add(ClassSubject(class_id=class_id, school_subject_id=subject_id))

    run(seed())
    ready = runtime.client.get("/api/v1/students/me/onboarding")
    assert ready.status_code == 200, ready.text
    assert ready.json()["complete"] is True

    async def bank():
        async with runtime.sessions.begin() as session:
            student = await session.get(User, runtime.ids["student"])
            assert (
                student.baseline_profile["subject_placement_statuses"][str(subject_id)]["status"]
                == "unestablished"
            )
            assert not student.baseline_profile.get("subject_placements")
            session.add(
                ProbeItem(
                    school_id=runtime.ids["school"],
                    school_subject_id=subject_id,
                    lesson_id=runtime.ids["lesson"],
                    concept_id=runtime.ids["concept"],
                    question="How many fifths make a whole?",
                    options=[{"value": "a", "label": "Five"}, {"value": "b", "label": "Two"}],
                    correct_option="a",
                    difficulty=0.5,
                )
            )

    run(bank())
    lesson = runtime.ids["lesson"]
    ready = runtime.client.get(f"/api/v1/students/me/onboarding?lessonId={lesson}")
    assert ready.status_code == 200, ready.text
    assert ready.json()["nextModule"] == "domain_probe"
    assert ready.json()["returnTo"] == f"/student/lessons/{lesson}"
    assert ready.json()["probeSubjectId"] == str(subject_id)
    assert all(row["completed"] for row in ready.json()["modules"][:3])
    item = runtime.client.get(f"/api/v1/probe/{subject_id}/next?lessonId={lesson}")
    assert item.status_code == 200, item.text
    finished = runtime.client.post(
        f"/api/v1/probe/{subject_id}/answer",
        json={
            "itemId": item.json()["itemId"],
            "chosenOption": "a",
            "lessonId": str(lesson),
        },
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["navigatesTo"] == f"/student/lessons/{lesson}"


def test_word_conflict_contract_accepts_conditions_and_withholds_measurement(runtime):
    from nevo.db.models.account import User

    trials = [
        {
            "dimension": "interference_control",
            "condition": condition,
            "correct": True if condition == "congruent" else index < 8,
            "responseTimeMs": 700 if condition == "congruent" else 1100,
        }
        for condition in ("congruent", "incongruent")
        for index in range(12)
    ]
    result = runtime.client.post(
        "/api/baseline/trials", json={"sessionId": "word-conflict", "trials": trials}
    )
    assert result.status_code == 200, result.text
    assert result.json()["baselineProfile"] == {}
    assert result.json()["engineConfig"]["support"]["simplifiedLayout"] is True

    async def verify():
        async with runtime.sessions() as session:
            student = await session.get(User, runtime.ids["student"])
            measurement = student.baseline_profile["measurements"]["interference_control"]
            assert measurement["status"] == "established"
            assert "trials" not in measurement

    run(verify())
