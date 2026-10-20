from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from nevo.api.auth import authenticated_principal
from nevo.api.safety_retention import router
from nevo.auth.entities import AuthPrincipal
from nevo.db.models.account import User
from nevo.db.models.safety import ContentSafetyEvent
from tests.intelligence.test_learning_runtime_endpoints import (
    run,
)
from tests.intelligence.test_learning_runtime_endpoints import (
    runtime as runtime_fixture,
)


@pytest.fixture(name="runtime")
def compliance_runtime(monkeypatch):
    yield from runtime_fixture.__wrapped__(monkeypatch)


def test_safeguarding_queue_is_role_scoped_content_free_and_acknowledged(runtime):
    runtime.client.app.include_router(router)
    actor_id, event_id = uuid4(), uuid4()

    async def seed():
        async with runtime.sessions.begin() as session:
            session.add(
                User(
                    id=actor_id,
                    school_id=runtime.ids["school"],
                    role="senco_admin",
                    auth_method="email_password",
                    status="active",
                    first_name="Reviewer",
                    email_confirmed_at=datetime.now(UTC),
                )
            )
            await session.flush()
            session.add(
                ContentSafetyEvent(
                    id=event_id,
                    school_id=runtime.ids["school"],
                    student_id=runtime.ids["student"],
                    actor_user_id=runtime.ids["student"],
                    phase="input:ask_nevo.student",
                    action="safeguard",
                    categories=["self_harm"],
                    policy_version="test",
                    model="test",
                )
            )

    run(seed())
    url = "/api/v1/safety/events"
    assert runtime.client.get(url).status_code == 403
    principal = AuthPrincipal(actor_id, "senco_admin", uuid4())
    runtime.client.app.dependency_overrides[authenticated_principal] = lambda: principal
    result = runtime.client.get(url)
    assert result.status_code == 200, result.text
    event = result.json()[0]
    assert event["id"] == str(event_id)
    assert "question" not in event and "response" not in event
    first = runtime.client.post(f"{url}/{event_id}/acknowledge")
    assert first.status_code == 200, first.text
    assert first.json()["acknowledgedBy"] == str(actor_id)
    assert runtime.client.get(url).json() == []
    second = runtime.client.post(f"{url}/{event_id}/acknowledge")
    assert second.json()["acknowledgedAt"] == first.json()["acknowledgedAt"]
    assert runtime.client.post(f"{url}/{uuid4()}/acknowledge").status_code == 404


def test_end_purpose_sets_deadline_and_stops_access(runtime):
    runtime.client.app.include_router(router)

    async def promote():
        async with runtime.sessions.begin() as session:
            actor = await session.get(User, runtime.ids["teacher"])
            actor.role = "senco_admin"
            actor.email_confirmed_at = datetime.now(UTC)

    run(promote())
    principal = AuthPrincipal(runtime.ids["teacher"], "senco_admin", uuid4())
    runtime.client.app.dependency_overrides[authenticated_principal] = lambda: principal
    url = f"/api/v1/students/{runtime.ids['student']}/retention/end-purpose"
    result = runtime.client.post(url)
    assert result.status_code == 200, result.text
    payload = result.json()
    end = datetime.fromisoformat(payload["purposeEndedAt"].replace("Z", "+00:00"))
    due = datetime.fromisoformat(payload["purgeDueAt"].replace("Z", "+00:00"))
    assert due - end == timedelta(days=180)
    assert runtime.client.post(url).json()["purposeEndedAt"] == payload["purposeEndedAt"]

    async def verify():
        async with runtime.sessions() as session:
            student = await session.get(User, runtime.ids["student"])
            assert student.status.value == "deactivated"
            assert await session.scalar(select(User.id).where(User.id == student.id))

    run(verify())
