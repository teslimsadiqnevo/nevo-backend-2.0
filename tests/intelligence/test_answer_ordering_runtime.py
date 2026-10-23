import pytest

from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.product import LessonQuestionAttempt
from tests.intelligence.test_learning_runtime_endpoints import answer, run, start
from tests.intelligence.test_learning_runtime_endpoints import runtime as runtime_fixture


@pytest.fixture(name="runtime")
def ordering_runtime(monkeypatch):
    yield from runtime_fixture.__wrapped__(monkeypatch)


def test_online_offline_and_marked_snapshot_use_the_same_option_order(runtime):
    question = {
        "id": "q1",
        "prompt": "How many fifths make a whole?",
        "answerType": "single_choice",
        "answerKey": 5,
        "options": [{"value": n, "label": str(n)} for n in (5, 2, 3, 4)],
    }

    async def seed():
        async with runtime.sessions.begin() as session:
            segment = await session.get(LessonSegment, runtime.ids["segment"])
            segment.comprehension_checkpoints = [question]
            lesson = await session.get(Lesson, runtime.ids["lesson"])
            lesson.assessment = [dict(question, id="final")]

    run(seed())
    lesson_id = runtime.ids["lesson"]
    payloads = []
    for url in (
        f"/api/v1/lessons/{lesson_id}",
        f"/api/content/lessons/{lesson_id}",
        f"/api/v1/lessons/{lesson_id}/offline-package.json",
    ):
        response = runtime.client.get(url)
        assert response.status_code == 200, response.text
        payloads.append(response.json())
    options = payloads[0]["segments"][0]["comprehensionCheckpoints"][0]["options"]
    assert all(
        row["segments"][0]["comprehensionCheckpoints"][0]["options"] == options for row in payloads
    )
    assert all(
        row["assessment"][0]["options"] == payloads[0]["assessment"][0]["options"]
        for row in payloads
    )
    sitting = start(runtime)
    response = answer(runtime, sitting, 5)
    assert response.status_code == 201, response.text
    response = runtime.client.post(
        f"/api/v1/lessons/{lesson_id}/attempts",
        json={"sessionId": sitting, "source": "assessment", "questionId": "final", "answer": 5},
    )
    assert response.status_code == 201, response.text

    async def verify():
        from sqlalchemy import select

        async with runtime.sessions() as session:
            saved = await session.scalar(
                select(LessonQuestionAttempt).where(
                    LessonQuestionAttempt.student_id == runtime.ids["student"],
                    LessonQuestionAttempt.question_id == "q1",
                )
            )
            assert saved.question_snapshot["options"] == options
            assert saved.correct is True
            final = await session.scalar(
                select(LessonQuestionAttempt).where(
                    LessonQuestionAttempt.student_id == runtime.ids["student"],
                    LessonQuestionAttempt.question_id == "final",
                )
            )
            assert final.question_snapshot["options"] == payloads[0]["assessment"][0]["options"]
            assert final.correct is True

    run(verify())


def test_quarantined_import_cannot_be_opened_by_a_student(runtime):
    async def quarantine():
        async with runtime.sessions.begin() as session:
            lesson = await session.get(Lesson, runtime.ids["lesson"])
            lesson.status = "failed"

    run(quarantine())
    response = runtime.client.get(f"/api/v1/lessons/{runtime.ids['lesson']}")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "lesson_content_requires_review"
