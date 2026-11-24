"""/me Phase 5: a learner sees their own mastery in three levels, and only theirs.

Done when: a learner sees their own mastery in three levels, cannot see
anyone else's, and the free tier shows a locked body with a 200.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

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


def _seed(sessions, email, *, levels, name="osmosis_basics"):
    """One own lesson and concept, with level rows: level -> (p, passes, days_ago)."""

    from nevo.db.models.account import User
    from nevo.db.models.content import Lesson
    from nevo.db.models.frontend_support import Concept
    from nevo.db.models.mastery import StudentConceptLevelMastery

    async def run():
        async with sessions.begin() as session:
            learner = await session.scalar(select(User).where(User.email == email))
            lesson = Lesson(
                created_by_user_id=learner.id, title="Osmosis", source_type="pdf",
                status="completed",
            )
            session.add(lesson)
            await session.flush()
            concept = Concept(name=name, lesson_id=lesson.id)
            session.add(concept)
            await session.flush()
            now = datetime.now(UTC)
            for level, (probability, passes, days_ago) in levels.items():
                session.add(
                    StudentConceptLevelMastery(
                        student_id=learner.id,
                        concept_id=concept.id,
                        mastery_level=level,
                        mastery_probability=probability,
                        practice_count=passes + 1,
                        independent_pass_count=passes,
                        supported_pass_count=0,
                        strengthened_at=(
                            now - timedelta(days=days_ago) if days_ago is not None else None
                        ),
                        last_updated=now,
                    )
                )
            return learner.id, concept.id

    return asyncio.run(run())


def _grant(sessions, learner_id, tier_key):
    from nevo.db.models.me import MePurchase

    async def run():
        async with sessions.begin() as session:
            now = datetime.now(UTC)
            session.add(
                MePurchase(
                    learner_id=learner_id, tier_key=tier_key, amount_minor=1, currency="NGN",
                    reference=f"nevo-me-test-{learner_id}-{tier_key}", status="success",
                    created_at=now, paid_at=now, period_start=now - timedelta(days=1),
                    period_end=now + timedelta(days=29),
                )
            )

    asyncio.run(run())


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


def test_mastery_is_three_levels_and_no_numbers(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    _seed(sessions, email, levels={"knowledge": (0.82, 2, 5), "application": (0.55, 1, None)})
    _seed(sessions, email, levels={"knowledge": (0.4, 0, None)}, name="diffusion")

    body = client.get("/api/v1/me/mastery", headers=auth).json()

    concepts = {item["conceptName"]: item for item in body["concepts"]}
    osmosis = next(item for name, item in concepts.items() if "smosis" in name)
    diffusion = next(item for name, item in concepts.items() if "iffusion" in name)
    assert osmosis["level"] == "knowledge"
    assert osmosis["workingTowards"] == "application"
    assert "level" not in diffusion
    assert diffusion["workingTowards"] == "knowledge"
    assert _numbers(body) == []  # no score, percentage or count anywhere


def test_a_level_needs_the_ones_below_it(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    _seed(sessions, email, levels={"knowledge": (0.3, 0, None), "application": (0.9, 3, 2)})

    concept = client.get("/api/v1/me/mastery", headers=auth).json()["concepts"][0]

    assert "level" not in concept
    assert concept["workingTowards"] == "knowledge"


def test_a_learner_reads_only_themselves(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    other_email, _ = _signed_in(client, mailer)
    own_id, _ = _seed(sessions, email, levels={"knowledge": (0.9, 2, 1)})
    other_id, _ = _seed(sessions, other_email, levels={"knowledge": (0.9, 2, 1)}, name="theirs")

    names = [item["conceptName"] for item in client.get(
        "/api/v1/me/mastery", headers=auth
    ).json()["concepts"]]

    assert all("heirs" not in name for name in names)
    assert client.get(f"/api/mastery/student/{own_id}", headers=auth).status_code == 200
    assert client.get(f"/api/mastery/student/{other_id}", headers=auth).status_code == 404


def test_free_tier_progress_is_a_locked_200(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    _seed(sessions, email, levels={"knowledge": (0.9, 2, 3)})

    response = client.get("/api/v1/me/progress", headers=auth)

    assert response.status_code == 200
    assert response.json() == {"locked": True, "unlocksWith": "monthly_12"}


def test_first_paid_tier_sees_a_rolling_window(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    learner_id, _ = _seed(sessions, email, levels={"knowledge": (0.9, 2, 10)})
    _seed(sessions, email, levels={"knowledge": (0.9, 2, 200)}, name="old_topic")
    _grant(sessions, learner_id, "monthly_12")

    body = client.get("/api/v1/me/progress", headers=auth).json()

    assert body["locked"] is False
    assert body["window"] == "rolling"
    assert len(body["events"]) == 1
    assert body["events"][0]["level"] == "knowledge"


def test_top_tier_sees_the_full_history(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    learner_id, _ = _seed(sessions, email, levels={"knowledge": (0.9, 2, 10)})
    _seed(sessions, email, levels={"knowledge": (0.9, 2, 200)}, name="old_topic")
    _grant(sessions, learner_id, "monthly_25")

    body = client.get("/api/v1/me/progress", headers=auth).json()

    assert body["window"] == "full"
    assert "since" not in body
    assert len(body["events"]) == 2
