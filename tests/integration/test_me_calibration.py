"""/me Phase 6: calibration, the waitlist and the enquiry.

Done when: a learner can predict before a check and see the gap after it;
the waitlist and enquiry both capture and notify.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from tests.integration.test_me_identity import URL, _address, _register

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]


def _signed_in(client, mailer):
    email = _address()
    _register(client, email, born=date(2001, 5, 1))
    token = client.post(
        "/api/v1/auth/verify-email", json={"email": email, "code": mailer.code_for(email)}
    ).json()["accessToken"]
    return email, {"Authorization": f"Bearer {token}"}


def _own_lesson(sessions, email):
    from nevo.db.models.account import User
    from nevo.db.models.content import Lesson

    async def run():
        async with sessions.begin() as session:
            learner = await session.scalar(select(User).where(User.email == email))
            lesson = Lesson(
                created_by_user_id=learner.id, title="Osmosis", source_type="pdf",
                status="completed",
            )
            session.add(lesson)
            await session.flush()
            return learner.id, lesson.id

    return asyncio.run(run())


def _answer(sessions, learner_id, lesson_id, answers, *, at=None):
    """answers: [(level, correct)], submitted now (or at a given moment)."""

    from nevo.db.models.product import LessonQuestionAttempt
    from nevo.db.models.signal_event import LessonSession

    async def run():
        async with sessions.begin() as session:
            lesson_session = LessonSession(
                id=uuid4(), student_id=learner_id, started_at=datetime.now(UTC)
            )
            session.add(lesson_session)
            await session.flush()
            for number, (level, correct) in enumerate(answers, start=1):
                session.add(
                    LessonQuestionAttempt(
                        student_id=learner_id,
                        lesson_id=lesson_id,
                        session_id=lesson_session.id,
                        question_id=f"q-{uuid4()}",
                        source="checkpoint",
                        attempt_number=number,
                        question_snapshot={"masteryLevel": level, "prompt": "?"},
                        answer="a",
                        correct=correct,
                        submitted_at=at or datetime.now(UTC),
                    )
                )

    asyncio.run(run())


def _predict(client, auth, lesson_id, level):
    return client.post(
        f"/api/v1/me/checks/{lesson_id}/prediction", headers=auth, json={"level": level}
    )


def _numbers(value):
    if isinstance(value, bool):
        return []
    if isinstance(value, int | float):
        return [value]
    if isinstance(value, dict):
        return [n for item in value.values() for n in _numbers(item)]
    if isinstance(value, list):
        return [n for item in value for n in _numbers(item)]
    return []


def test_overconfident_by_one_level(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    learner_id, lesson_id = _own_lesson(sessions, email)

    made = _predict(client, auth, lesson_id, "analysis")
    assert made.status_code == 201
    assert made.json()["answered"] is False
    assert "gap" not in made.json()

    _answer(
        sessions, learner_id, lesson_id,
        [("knowledge", True), ("application", True), ("analysis", False)],
    )
    body = client.get(f"/api/v1/me/checks/{lesson_id}/prediction", headers=auth).json()

    assert body["reached"] == "application"
    assert body["gap"] == "over_by_one"
    assert _numbers(body) == []


def test_underconfident_by_one_level(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    learner_id, lesson_id = _own_lesson(sessions, email)
    _predict(client, auth, lesson_id, "knowledge")
    _answer(sessions, learner_id, lesson_id, [("application", True)])

    body = client.get(f"/api/v1/me/checks/{lesson_id}/prediction", headers=auth).json()

    assert body["gap"] == "under_by_one"


def test_answering_and_reaching_nothing_is_still_a_gap(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    learner_id, lesson_id = _own_lesson(sessions, email)
    _predict(client, auth, lesson_id, "analysis")
    _answer(sessions, learner_id, lesson_id, [("knowledge", False)])

    body = client.get(f"/api/v1/me/checks/{lesson_id}/prediction", headers=auth).json()

    assert body["answered"] is True
    assert "reached" not in body
    assert body["gap"] == "over_by_three"


def test_each_prediction_is_judged_on_its_own_attempts_and_kept_over_time(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    learner_id, lesson_id = _own_lesson(sessions, email)
    _predict(client, auth, lesson_id, "knowledge")
    _answer(sessions, learner_id, lesson_id, [("knowledge", True)])
    _predict(client, auth, lesson_id, "analysis")

    latest = client.get(f"/api/v1/me/checks/{lesson_id}/prediction", headers=auth).json()
    history = client.get("/api/v1/me/calibration", headers=auth).json()["checks"]

    assert latest["predicted"] == "analysis_and_evaluation"
    assert latest["answered"] is False  # the earlier answer belongs to the earlier one
    assert [item["predicted"] for item in history] == [
        "analysis_and_evaluation",
        "knowing_and_understanding",
    ]
    assert history[1]["gap"] == "matched"


def test_attempts_before_the_prediction_do_not_count(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    learner_id, lesson_id = _own_lesson(sessions, email)
    _answer(
        sessions, learner_id, lesson_id, [("analysis", True)],
        at=datetime.now(UTC) - timedelta(hours=1),
    )

    made = _predict(client, auth, lesson_id, "knowledge").json()

    assert made["answered"] is False


def test_only_on_a_lesson_of_ones_own(me):
    client, mailer, sessions = me
    _, auth = _signed_in(client, mailer)
    other_email, _ = _signed_in(client, mailer)
    _, theirs = _own_lesson(sessions, other_email)

    assert _predict(client, auth, theirs, "knowledge").status_code == 404
    assert _predict(client, auth, uuid4(), "knowledge").status_code == 404


def test_a_prediction_is_one_of_the_three_levels(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    _, lesson_id = _own_lesson(sessions, email)

    assert _predict(client, auth, lesson_id, "expert").status_code == 422


def _requests(sessions, email, kind):
    from nevo.db.models.me import MeContactRequest

    async def run():
        async with sessions() as session:
            return await session.scalar(
                select(func.count()).select_from(MeContactRequest).where(
                    MeContactRequest.email == email, MeContactRequest.kind == kind
                )
            )

    return asyncio.run(run())


def test_the_waitlist_captures_and_notifies_once(me, monkeypatch):
    client, mailer, sessions = me
    monkeypatch.setenv("LEAD_ALERT_RECIPIENTS", "team@nevolearning-tests.com")
    email = _address()

    first = client.post("/api/v1/me/waitlist", json={"email": email, "note": "Exam in May"})
    again = client.post("/api/v1/me/waitlist", json={"email": email})

    assert first.status_code == again.status_code == 202
    assert _requests(sessions, email, "waitlist") == 1
    alerts = [item for item in mailer.sent if item["to"] == "team@nevolearning-tests.com"]
    assert len([item for item in alerts if email in item["subject"]]) == 1


def test_an_enquiry_needs_no_account_and_says_who(me, monkeypatch):
    client, mailer, sessions = me
    monkeypatch.setenv("LEAD_ALERT_RECIPIENTS", "team@nevolearning-tests.com")
    email = _address()

    response = client.post(
        "/api/v1/me/enquiry",
        json={"email": email, "who": "tutorial_centre", "name": "Bright Minds", "note": "40"},
    )

    assert response.status_code == 202
    assert _requests(sessions, email, "enquiry") == 1
    alert = [item for item in mailer.sent if email in item["subject"]][-1]
    assert "tutorial_centre" in alert["text"]
    assert client.post("/api/v1/me/enquiry", json={"email": email}).status_code == 422
