import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from nevo.api.auth import authenticated_principal
from nevo.api.learning_support import refuse_last_holder_change
from nevo.api.safety_retention import router
from nevo.auth.entities import AuthPrincipal
from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.permission import LearningSupportGrant
from nevo.db.models.safety import ContentSafetyEvent
from nevo.db.models.teacher_assignment import TeacherClassAssignment
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
            class_id = uuid4()
            session.add(
                Class(
                    id=class_id, school_id=runtime.ids["school"], name="P4", academic_session="2026"
                )
            )
            await session.flush()
            session.add(
                StudentClassEnrollment(student_id=runtime.ids["student"], class_id=class_id)
            )
            session.add(
                TeacherClassAssignment(
                    school_id=runtime.ids["school"],
                    teacher_id=runtime.ids["teacher"],
                    class_id=class_id,
                    role="primary",
                    source="manual",
                )
            )
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
    assert runtime.client.get(url).status_code == 403

    async def grant():
        async with runtime.sessions.begin() as session:
            session.add(
                LearningSupportGrant(
                    school_id=runtime.ids["school"],
                    holder_user_id=actor_id,
                    granted_by_user_id=actor_id,
                )
            )

    run(grant())
    result = runtime.client.get(url)
    assert result.status_code == 200, result.text
    event = result.json()[0]
    assert event["id"] == str(event_id)
    assert "question" not in event and "response" not in event
    first = runtime.client.post(f"{url}/{event_id}/acknowledge")
    assert first.status_code == 200, first.text
    assert first.json()["acknowledgedBy"] == str(actor_id)
    assert first.json()["acknowledgedByName"] == "Reviewer"
    assert first.json()["studentName"]
    assert runtime.client.get(url).json() == []
    second = runtime.client.post(f"{url}/{event_id}/acknowledge")
    assert second.json()["acknowledgedAt"] == first.json()["acknowledgedAt"]
    assert runtime.client.post(f"{url}/{uuid4()}/acknowledge").status_code == 404
    profile_url = f"/api/v1/students/{runtime.ids['student']}/profile"
    profile = runtime.client.get(profile_url)
    assert profile.status_code == 200, profile.text
    line = profile.json()["safeguardingAcknowledgements"][0]
    assert line["eventId"] == str(event_id)
    assert line["acknowledgedByName"] == "Reviewer"
    teacher = AuthPrincipal(runtime.ids["teacher"], "teacher", uuid4())
    runtime.client.app.dependency_overrides[authenticated_principal] = lambda: teacher
    assert runtime.client.get(url).status_code == 403
    ordinary_profile = runtime.client.get(profile_url)
    assert ordinary_profile.status_code == 200, ordinary_profile.text
    assert ordinary_profile.json()["safeguardingAcknowledgements"] == []


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


def test_concurrent_holder_removals_preserve_one_active_holder(runtime):
    admin_id = uuid4()

    async def exercise():
        async with runtime.sessions.begin() as session:
            session.add(
                User(
                    id=admin_id,
                    school_id=runtime.ids["school"],
                    role="other_admin",
                    auth_method="email_password",
                    status="active",
                    first_name="Support",
                )
            )
            await session.flush()
            for holder_id in (admin_id, runtime.ids["teacher"]):
                session.add(
                    LearningSupportGrant(
                        school_id=runtime.ids["school"],
                        holder_user_id=holder_id,
                        granted_by_user_id=admin_id,
                    )
                )

        async def remove(holder_id):
            try:
                async with runtime.sessions.begin() as session:
                    await refuse_last_holder_change(
                        session,
                        school_id=runtime.ids["school"],
                        user_id=holder_id,
                        operation="remove_role",
                    )
                    grant = await session.scalar(
                        select(LearningSupportGrant).where(
                            LearningSupportGrant.holder_user_id == holder_id,
                            LearningSupportGrant.revoked_at.is_(None),
                        )
                    )
                    grant.revoked_at = datetime.now(UTC)
                    await asyncio.sleep(0.05)
                return "removed"
            except HTTPException as error:
                assert error.status_code == 409
                return error.detail["code"]

        results = await asyncio.gather(remove(admin_id), remove(runtime.ids["teacher"]))
        assert sorted(results) == ["last_learning_support_holder", "removed"]

    run(exercise())
