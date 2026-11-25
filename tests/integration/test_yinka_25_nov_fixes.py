"""S14, S16 and S13 from the frontend's 25 November list, against a real database."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from tests.integration.test_me_identity import URL

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]


def _school_with_people(sessions):
    from nevo.db.models.account import Class, School, StudentClassEnrollment, User

    async def run():
        async with sessions.begin() as session:
            school = School(
                name="S", school_code=uuid.uuid4().hex[:4].upper(),
                school_url_slug=f"s-{uuid.uuid4().hex[:8]}",
            )
            session.add(school)
            await session.flush()

            def person(role, **extra):
                return User(
                    school_id=school.id, role=role, status="active",
                    auth_method="email_password",
                    email=f"{role}-{uuid.uuid4().hex[:6]}@nevolearning-tests.com", **extra,
                )

            people = {
                "plain_admin": person("other_admin"),
                "ls_admin": person("other_admin"),
                "teacher": person("teacher"),
                "child": User(
                    school_id=school.id, role="student", status="active", auth_method="pin",
                    login_identifier=f"NV-{uuid.uuid4().hex[:6]}",
                ),
            }
            session.add_all(people.values())
            await session.flush()
            school_class = Class(school_id=school.id, name=f"JSS {uuid.uuid4().hex[:3]}")
            session.add(school_class)
            await session.flush()
            session.add(
                StudentClassEnrollment(student_id=people["child"].id, class_id=school_class.id)
            )
            from nevo.db.models.permission import LearningSupportGrant

            session.add(
                LearningSupportGrant(
                    school_id=school.id, holder_user_id=people["ls_admin"].id,
                    granted_by_user_id=people["ls_admin"].id,
                )
            )
            return school.id, school_class.id, {k: v.id for k, v in people.items()}

    return asyncio.run(run())


# -- S14 -------------------------------------------------------------------


def _class_students(sessions, user_id, role, class_id):
    from nevo.api.auth import authenticated_principal
    from nevo.api.dependencies import database_session
    from nevo.api.frontend_unblockers import router
    from nevo.auth.entities import AuthPrincipal
    from nevo.permissions.wiring import build_permission_service

    app = FastAPI()
    app.include_router(router)
    app.state.permission_service = build_permission_service(
        sessions, credential_hasher=None, session_pepper="x" * 48
    )

    async def db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[database_session] = db
    app.dependency_overrides[authenticated_principal] = lambda: AuthPrincipal(
        user_id=user_id, role=role, session_id=uuid.uuid4()
    )

    async def call():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            return await client.get(f"/api/v1/classes/{class_id}/students")

    return asyncio.run(call())


def test_an_admin_with_learning_support_reads_a_class_and_one_without_access_does_not(me):
    _, _, sessions = me
    _, class_id, people = _school_with_people(sessions)

    allowed = _class_students(sessions, people["ls_admin"], "other_admin", class_id)
    refused = _class_students(sessions, people["plain_admin"], "other_admin", class_id)
    stranger = _class_students(sessions, people["teacher"], "teacher", class_id)

    assert allowed.status_code == 200
    assert len(allowed.json()) == 1
    assert "observations" in allowed.json()[0]
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "class_students_forbidden"
    assert stranger.status_code == 404  # a teacher who does not teach it, as before


# -- S16 -------------------------------------------------------------------


def _event(session, school_id, student_id, *, action="block", categories=("self_harm",)):
    from nevo.db.models.safety import ContentSafetyEvent

    return ContentSafetyEvent(
        school_id=school_id, student_id=student_id, phase="input:ask_nevo",
        action=action, categories=list(categories), policy_version="t", model="t",
    )


def _notices(sessions, user_id, kind):
    from nevo.db.models.frontend_support import Notification

    async def run():
        async with sessions() as session:
            return list(
                await session.scalars(
                    select(Notification).where(
                        Notification.recipient_id == user_id, Notification.type == kind
                    )
                )
            )

    return asyncio.run(run())


def test_a_new_safeguarding_entry_notifies_each_holder_and_no_one_else(me):
    _, _, sessions = me
    school_id, _, people = _school_with_people(sessions)
    from nevo.ai_gateway.safety import ContentSafetyGuard

    async def record():
        async with sessions.begin() as session:
            row = _event(session, school_id, people["child"])
            session.add(row)
            await session.flush()
            await ContentSafetyGuard._tell_learning_support(session, row)

    asyncio.run(record())

    notices = _notices(sessions, people["ls_admin"], "safeguarding_flag")
    assert len(notices) == 1
    assert notices[0].category == "attention"
    assert _notices(sessions, people["plain_admin"], "safeguarding_flag") == []


def test_a_bare_name_finding_raises_nothing(me):
    _, _, sessions = me
    school_id, _, people = _school_with_people(sessions)
    from nevo.notifications.safeguarding import notify_learning_support

    async def record():
        async with sessions.begin() as session:
            row = _event(session, school_id, people["child"], categories=("privacy_abuse",))
            session.add(row)
            await session.flush()
            return await notify_learning_support(session, row)

    assert asyncio.run(record()) == 0


def test_a_failing_notification_never_loses_the_safety_record(me, monkeypatch):
    _, _, sessions = me
    school_id, _, people = _school_with_people(sessions)
    from nevo.ai_gateway.safety import ContentSafetyGuard
    from nevo.db.models.safety import ContentSafetyEvent
    from nevo.notifications import safeguarding

    async def explode(session, event):
        raise RuntimeError("notification store down")

    monkeypatch.setattr(safeguarding, "notify_learning_support", explode)

    async def record():
        async with sessions.begin() as session:
            row = _event(session, school_id, people["child"])
            session.add(row)
            await session.flush()
            await ContentSafetyGuard._tell_learning_support(session, row)
            return row.id

    event_id = asyncio.run(record())

    async def kept():
        async with sessions() as session:
            return await session.get(ContentSafetyEvent, event_id)

    assert asyncio.run(kept()) is not None


# -- S13 -------------------------------------------------------------------


def test_a_failing_sync_keeps_one_notice_until_a_sync_succeeds(me):
    _, _, sessions = me
    school_id, _, people = _school_with_people(sessions)
    from nevo.db.models.sso import RosterSyncRun
    from nevo.domain.accounts.vocabulary import SsoProvider
    from nevo.sso.repositories import FAILED_SYNC_TITLE, _notify_failed_sync_once

    async def fail(reason):
        async with sessions.begin() as session:
            await _notify_failed_sync_once(
                session, school_id=school_id, provider=SsoProvider.GOOGLE,
                description=f"Google refused the last sync: {reason}",
                failed_at=datetime.now(UTC),
            )

    asyncio.run(fail("first"))
    asyncio.run(fail("second"))
    asyncio.run(fail("third"))

    notices = [
        n for n in _notices(sessions, people["plain_admin"], "sso_needs_attention")
        if n.title == FAILED_SYNC_TITLE
    ]
    assert len(notices) == 1
    assert notices[0].description.endswith("third")

    async def succeed():
        async with sessions.begin() as session:
            session.add(
                RosterSyncRun(
                    school_id=school_id, provider=SsoProvider.GOOGLE, status="completed",
                    started_at=datetime.now(UTC) + timedelta(seconds=1),
                    completed_at=datetime.now(UTC) + timedelta(seconds=1),
                )
            )

    asyncio.run(succeed())
    asyncio.run(asyncio.sleep(1.2))
    asyncio.run(fail("after recovery"))

    count = len([
        n for n in _notices(sessions, people["plain_admin"], "sso_needs_attention")
        if n.title == FAILED_SYNC_TITLE
    ])
    assert count == 2
