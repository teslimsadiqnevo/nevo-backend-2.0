"""A /me learner opens and works through their own lesson.

The lesson player, opened to individual accounts: their own lessons only,
with no teacher review gate (INDIVIDUAL_LESSONS_NEED_TEACHER_REVIEW), and
the calibration gap riding on the check result when they predicted first.
"""

import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select

from tests.integration.test_me_identity import URL, _address, _register

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]

READY = {
    "completed_modules": ["grid_span", "pattern_flanker", "sentence_dot", "domain_probe"],
    "domain_probe_status": "unavailable_at_onboarding",
}


def _signed_in(client, mailer):
    email = _address()
    _register(client, email, born=date(2001, 5, 1))
    token = client.post(
        "/api/v1/auth/verify-email", json={"email": email, "code": mailer.code_for(email)}
    ).json()["accessToken"]
    return email, {"Authorization": f"Bearer {token}"}


def _seed_lesson(sessions, email, *, needs_review=False):
    from nevo.api.lesson_contracts import checkpoint_payloads
    from nevo.db.models.account import User
    from nevo.db.models.content import ContentParseRun, Lesson, LessonSegment
    from nevo.db.models.frontend_support import Concept

    async def run():
        async with sessions.begin() as session:
            learner = await session.scalar(select(User).where(User.email == email))
            learner.baseline_profile = {**(learner.baseline_profile or {}), **READY}
            lesson = Lesson(
                created_by_user_id=learner.id, title="Osmosis", source_type="pdf",
                status="completed", segment_count=1,
            )
            session.add(lesson)
            await session.flush()
            run_row = ContentParseRun(
                lesson_id=lesson.id, requested_by_user_id=learner.id, source_type="pdf"
            )
            concept = Concept(name="osmosis", lesson_id=lesson.id)
            session.add_all([run_row, concept])
            await session.flush()
            checkpoints = checkpoint_payloads(
                [
                    {
                        "id": "q1",
                        "prompt": "What moves across the membrane in osmosis?",
                        "answerType": "single_choice",
                        "options": [
                            {"value": "water", "label": "Water"},
                            {"value": "salt", "label": "Salt"},
                        ],
                        "answerKey": "water",
                        "masteryLevel": "knowledge",
                    }
                ],
                segment_key="s1",
                concept_id=concept.id,
            )
            segment = LessonSegment(
                lesson_id=lesson.id,
                parse_run_id=run_row.id,
                segment_key="s1",
                content_type="explanatory_text",
                sequence_order=1,
                body="Osmosis is the movement of water across a membrane.",
                available_modalities=["text"],
                concept_id=concept.id,
                comprehension_checkpoints=checkpoints,
                needs_review=needs_review,
            )
            session.add(segment)
            await session.flush()
            return lesson.id, segment.id, checkpoints[0]

    return asyncio.run(run())


def test_a_learner_opens_and_starts_their_own_lesson(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    lesson_id, _, _ = _seed_lesson(sessions, email)

    detail = client.get(f"/api/v1/lessons/{lesson_id}", headers=auth)
    started = client.post(f"/api/v1/lessons/{lesson_id}/session", headers=auth, json={})

    assert detail.status_code == 200, detail.json()
    assert started.status_code == 201, started.json()
    assert "sessionId" in started.json()


def test_another_learners_lesson_is_not_there(me):
    client, mailer, sessions = me
    _, auth = _signed_in(client, mailer)
    other_email, _ = _signed_in(client, mailer)
    theirs, _, _ = _seed_lesson(sessions, other_email)

    assert client.get(f"/api/v1/lessons/{theirs}", headers=auth).status_code == 404
    started = client.post(f"/api/v1/lessons/{theirs}/session", headers=auth, json={})
    assert started.status_code == 404
    assert client.get(f"/api/v1/lessons/{uuid4()}", headers=auth).status_code == 404


def test_the_check_result_carries_the_calibration_gap(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    lesson_id, segment_id, checkpoint = _seed_lesson(sessions, email)
    session_id = client.post(
        f"/api/v1/lessons/{lesson_id}/session", headers=auth, json={}
    ).json()["sessionId"]
    client.post(
        f"/api/v1/me/checks/{lesson_id}/prediction", headers=auth, json={"level": "application"}
    )

    answered = client.post(
        f"/api/v1/lessons/{lesson_id}/attempts",
        headers=auth,
        json={
            "sessionId": session_id,
            "questionId": checkpoint["id"],
            "segmentId": str(segment_id),
            "answer": checkpoint.get("answerKey", "water"),
            "responseTimeMs": 9000,
        },
    )

    assert answered.status_code == 201, answered.json()
    body = answered.json()
    assert body["correct"] is True
    assert body["calibration"] == {
        "predicted": "application",
        "reached": "knowledge",
        "gap": "over_by_one",
    }


def test_no_prediction_means_no_calibration_key(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    lesson_id, segment_id, checkpoint = _seed_lesson(sessions, email)
    session_id = client.post(
        f"/api/v1/lessons/{lesson_id}/session", headers=auth, json={}
    ).json()["sessionId"]

    answered = client.post(
        f"/api/v1/lessons/{lesson_id}/attempts",
        headers=auth,
        json={
            "sessionId": session_id,
            "questionId": checkpoint["id"],
            "segmentId": str(segment_id),
            "answer": checkpoint.get("answerKey", "water"),
            "responseTimeMs": 9000,
        },
    )

    assert answered.status_code == 201
    assert "calibration" not in answered.json()


def test_an_own_lesson_needs_no_teacher_sign_off(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    lesson_id, _, _ = _seed_lesson(sessions, email, needs_review=True)

    detail = client.get(f"/api/v1/lessons/{lesson_id}", headers=auth)

    assert detail.status_code == 200
    assert len(detail.json()["segments"]) == 1


def test_the_review_switch_puts_the_teacher_gate_back(me, monkeypatch):
    """If Lydia rules that a learner's own lesson waits for review, one flag."""

    from nevo.intelligence import learner_scope

    monkeypatch.setattr(learner_scope, "INDIVIDUAL_LESSONS_NEED_TEACHER_REVIEW", True)
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    lesson_id, segment_id, checkpoint = _seed_lesson(sessions, email)
    session_id = client.post(
        f"/api/v1/lessons/{lesson_id}/session", headers=auth, json={}
    ).json()["sessionId"]

    answered = client.post(
        f"/api/v1/lessons/{lesson_id}/attempts",
        headers=auth,
        json={
            "sessionId": session_id,
            "questionId": checkpoint["id"],
            "segmentId": str(segment_id),
            "answer": checkpoint.get("answerKey", "water"),
            "responseTimeMs": 9000,
        },
    )

    assert answered.status_code == 409
    assert answered.json()["detail"]["code"] == "lesson_content_requires_review"
