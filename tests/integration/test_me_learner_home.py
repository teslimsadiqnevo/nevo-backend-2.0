"""/me Phase 2: a learner with no school lands on a home that renders.

Done when: a learner with no school lands on a dashboard that renders, takes
the onboarding assessment, and has a baseline - and the response carries no
empty school-shaped keys.
"""

import asyncio
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from tests.integration.test_me_identity import URL, _address, _register

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]


def _signed_in(client, mailer, *, born=date(2001, 5, 1)):
    email = _address()
    _register(client, email, born=born)
    token = client.post(
        "/api/v1/auth/verify-email", json={"email": email, "code": mailer.code_for(email)}
    ).json()["accessToken"]
    return email, {"Authorization": f"Bearer {token}"}


def _seed_lessons(sessions, owner_email):
    """One completed lesson of the learner's own, one draft, and one of
    somebody else's - with a concept on each."""

    from nevo.db.models.account import User
    from nevo.db.models.content import Lesson
    from nevo.db.models.frontend_support import Concept

    async def run():
        async with sessions.begin() as session:
            owner = await session.scalar(select(User).where(User.email == owner_email))
            other = User(
                account_type="individual",
                role="student",
                auth_method="email_password",
                status="active",
                email=_address(),
            )
            session.add(other)
            await session.flush()
            lessons = {
                "mine": Lesson(
                    created_by_user_id=owner.id, title="Osmosis", source_type="pdf",
                    status="completed",
                ),
                "draft": Lesson(
                    created_by_user_id=owner.id, title="Draft", source_type="pdf",
                    status="pending",
                ),
                "theirs": Lesson(
                    created_by_user_id=other.id, title="Not yours", source_type="pdf",
                    status="completed",
                ),
            }
            session.add_all(lessons.values())
            await session.flush()
            concepts = {
                key: Concept(name=f"{key} concept", lesson_id=lesson.id)
                for key, lesson in lessons.items()
            }
            session.add_all(concepts.values())
            await session.flush()
            return (
                owner.id,
                {key: lesson.id for key, lesson in lessons.items()},
                {key: concept.id for key, concept in concepts.items()},
            )

    return asyncio.run(run())


def test_the_dashboard_renders_with_no_school_shaped_keys(me):
    client, mailer, _ = me
    _, auth = _signed_in(client, mailer)

    response = client.get("/api/v1/students/me/dashboard", headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert "assignments" not in body  # omitted, not []
    assert body["student"]["firstName"] == "Ada"
    assert body["recentProgress"] == []
    assert body["onboardingComplete"] is False


def test_an_under_18_waiting_on_a_guardian_still_has_a_home(me):
    client, mailer, _ = me
    today = datetime.now(UTC).date()
    _, auth = _signed_in(client, mailer, born=date(today.year - 16, 1, 1))

    assert client.get("/api/v1/students/me/dashboard", headers=auth).status_code == 200
    assert client.get("/api/v1/students/me/onboarding", headers=auth).status_code == 200


def test_onboarding_renders_and_records_no_fabricated_placement(me):
    client, mailer, _ = me
    _, auth = _signed_in(client, mailer)

    response = client.get("/api/v1/students/me/onboarding", headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert body["subjects"] == []
    modules = {item["id"]: item for item in body["modules"]}
    # No school subjects means no probe to place them with: said, not faked.
    assert modules["domain_probe"]["status"] == "unavailable"
    assert body["complete"] is False


def test_the_lesson_list_is_the_learners_own_and_omits_school_keys(me):
    client, mailer, sessions = me
    email, auth = _signed_in(client, mailer)
    assert client.get("/api/v1/lessons", headers=auth).json() == []

    _, lessons, _ = _seed_lessons(sessions, email)
    listed = client.get("/api/v1/lessons", headers=auth).json()

    assert {item["id"] for item in listed} == {str(lessons["mine"]), str(lessons["draft"])}
    for item in listed:
        for key in ("assignmentCount", "classNames", "canAssign", "createdById"):
            assert key not in item


def test_the_scope_reaches_own_completed_lessons_and_their_concepts_only(me):
    client, mailer, sessions = me
    email, _ = _signed_in(client, mailer)
    owner_id, lessons, concepts = _seed_lessons(sessions, email)

    from nevo.db.models.account import User
    from nevo.db.models.frontend_support import Concept
    from nevo.intelligence.learner_scope import available_lesson_ids, learner_concepts
    from nevo.intelligence.progression import next_work

    async def run():
        async with sessions() as session:
            owner = await session.get(User, owner_id)
            available = set(
                await session.scalars(available_lesson_ids(owner, datetime.now(UTC)))
            )
            reachable = set(
                await session.scalars(select(Concept.id).where(learner_concepts(owner)))
            )
            work = await next_work(session, owner)
            return available, reachable, work

    available, reachable, work = asyncio.run(run())
    assert available == {lessons["mine"]}
    assert reachable == {concepts["mine"], concepts["draft"]}
    assert work is None  # no segments yet: nothing to do, and no error


def test_the_baseline_assessment_records_for_an_individual(me):
    client, mailer, _ = me
    _, auth = _signed_in(client, mailer)

    submitted = client.post(
        "/api/baseline/submit",
        headers=auth,
        json={
            "sessionId": "11111111-1111-4111-8111-111111111111",
            "features": [{"module": "grid_span", "roundsCompleted": 2}],
        },
    )

    assert submitted.status_code == 200
    modules = {
        item["id"]: item
        for item in client.get("/api/v1/students/me/onboarding", headers=auth).json()["modules"]
    }
    assert modules["grid_span"]["completed"] is True
    assert modules["pattern_flanker"]["completed"] is False
