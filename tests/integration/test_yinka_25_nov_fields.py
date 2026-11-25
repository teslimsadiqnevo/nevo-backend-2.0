"""S8 and S10 from the frontend's 25 November list, against a real database."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI

from tests.integration.test_me_identity import URL

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]


def _call(sessions, router, path, user_id, role):
    from nevo.api.auth import authenticated_principal
    from nevo.api.dependencies import database_session
    from nevo.auth.entities import AuthPrincipal

    app = FastAPI()
    app.include_router(router)

    async def db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[database_session] = db
    app.dependency_overrides[authenticated_principal] = lambda: AuthPrincipal(
        user_id=user_id, role=role, session_id=uuid.uuid4()
    )

    async def go():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            return await client.get(path)

    return asyncio.run(go())


def _school(session):
    from nevo.db.models.account import School

    school = School(
        name="S", school_code=uuid.uuid4().hex[:4].upper(),
        school_url_slug=f"s-{uuid.uuid4().hex[:8]}",
    )
    session.add(school)
    return school


def test_every_invitation_row_carries_its_classes(me):
    _, _, sessions = me
    from nevo.api.product_auth import SchoolInvitation, router
    from nevo.db.models.account import Class, User
    from nevo.db.models.invitation_class import SchoolInvitationClass
    from nevo.db.models.subject import SchoolSubject

    async def seed():
        async with sessions.begin() as session:
            school = _school(session)
            await session.flush()
            admin = User(
                school_id=school.id, role="senco_admin", status="active",
                auth_method="email_password",
                email=f"a-{uuid.uuid4().hex[:6]}@nevolearning-tests.com",
            )
            jss = Class(school_id=school.id, name="JSS 2A")
            biology = SchoolSubject(
                school_id=school.id, name="Biology", normalised_name="biology", origin="school"
            )
            session.add_all([admin, jss, biology])
            await session.flush()
            invitations = []
            for with_classes in (True, False):
                invitation = SchoolInvitation(
                    school_id=school.id, role="teacher", token_digest=uuid.uuid4().hex,
                    email=f"t-{uuid.uuid4().hex[:6]}@nevolearning-tests.com",
                    expires_at=datetime.now(UTC) + timedelta(days=7), created_by_id=admin.id,
                )
                session.add(invitation)
                await session.flush()
                if with_classes:
                    session.add(
                        SchoolInvitationClass(
                            invitation_id=invitation.id, class_id=jss.id,
                            school_subject_id=biology.id,
                        )
                    )
                invitations.append(invitation.id)
            return admin.id, invitations

    admin_id, (with_classes, without) = asyncio.run(seed())
    rows = {
        row["id"]: row
        for row in _call(sessions, router, "/api/v1/invites", admin_id, "senco_admin").json()
    }

    assert rows[str(with_classes)]["classes"] == [
        {
            "classId": rows[str(with_classes)]["classes"][0]["classId"],
            "className": "JSS 2A",
            "subjectId": rows[str(with_classes)]["classes"][0]["subjectId"],
            "subjectName": "Biology",
        }
    ]
    assert rows[str(without)]["classes"] == []


def test_a_help_seeking_topic_below_the_floor_is_not_listed(me):
    _, _, sessions = me
    from nevo.api.insights import router
    from nevo.db.models.account import User
    from nevo.db.models.ask_nevo import AskNevoInteraction
    from nevo.db.models.permission import LearningSupportGrant

    async def seed():
        async with sessions.begin() as session:
            school = _school(session)
            await session.flush()
            admin = User(
                school_id=school.id, role="senco_admin", status="active",
                auth_method="email_password",
                email=f"a-{uuid.uuid4().hex[:6]}@nevolearning-tests.com",
            )
            child = User(
                school_id=school.id, role="student", status="active", auth_method="pin",
                login_identifier=f"NV-{uuid.uuid4().hex[:6]}",
            )
            session.add_all([admin, child])
            await session.flush()
            session.add(
                LearningSupportGrant(
                    school_id=school.id, holder_user_id=admin.id, granted_by_user_id=admin.id
                )
            )
            for category, times in (("lesson_help", 3), ("general", 1)):
                for _ in range(times):
                    session.add(
                        AskNevoInteraction(
                            actor_user_id=child.id, role="student", current_page="/lesson",
                            question_category=category,
                            context_ids={"studentId": str(child.id)},
                        )
                    )
            return admin.id, child.id

    admin_id, child_id = asyncio.run(seed())
    body = _call(
        sessions, router, f"/api/conversation-evidence/student/{child_id}", admin_id, "senco_admin"
    ).json()

    assert body["categories"] == {"lesson_help": 3}
    assert body["interactionCount"] == 4
