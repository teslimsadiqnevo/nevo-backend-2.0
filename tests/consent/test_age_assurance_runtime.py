"""Real database and HTTP checks; never point these tests at a school database."""

import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nevo.api.age_checks import router
from nevo.api.auth import authenticated_principal
from nevo.api.auth import router as auth_router
from nevo.api.dependencies import database_session
from nevo.auth.config import AuthSettings
from nevo.auth.repositories import SqlAlchemyUserRepository
from nevo.auth.wiring import build_auth_service
from nevo.consent.age_assurance import (
    discrepancy_exceeds_two_years,
    prepare_pending_holds,
    reconcile_school_date,
    record_parent_date,
)
from nevo.db.models.account import Class, School, StudentClassEnrollment, User
from nevo.db.models.consent import ParentLink
from nevo.db.models.consent_assurance import AgeCheck
from nevo.db.models.frontend_support import Notification
from nevo.db.models.signal_event import SignalEvent
from nevo.retention.service import RetentionService

URL = os.getenv("NEVO_RUNTIME_TEST_DATABASE_URL", "")


@pytest.mark.parametrize(
    "first,second,expected",
    [
        (date(2014, 3, 1), date(2016, 3, 1), False),
        (date(2014, 3, 1), date(2016, 3, 2), True),
        (date(2016, 2, 29), date(2018, 2, 28), False),
        (date(2016, 2, 29), date(2018, 3, 1), True),
    ],
)
def test_two_calendar_year_boundary(first, second, expected):
    assert discrepancy_exceeds_two_years(first, second) is expected
    assert discrepancy_exceeds_two_years(second, first) is expected


class Storage:
    configured = True

    def __init__(self, fail=False):
        self.fail = fail

    async def list_paths(self, prefix):
        return [prefix + "/proof.pdf"]

    async def delete(self, path):
        if self.fail:
            raise RuntimeError("Storage unavailable")


async def setup():
    parsed = make_url(URL)
    assert parsed.host in {"localhost", "127.0.0.1"}
    assert parsed.database == "nevo_adaptation_tests"
    engine = create_async_engine(URL, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    ids = {name: uuid4() for name in ("school", "child", "admin", "parent", "class", "outsider")}
    now = datetime.now(UTC)
    school_date = date(now.year - 10, 1, 1)
    async with sessions.begin() as session:
        session.add(
            School(
                id=ids["school"],
                name="DOB test",
                school_code=uuid4().hex[:8],
                school_url_slug=uuid4().hex,
                auth_method="email_password",
            )
        )
        await session.flush()
        for name, role in (
            ("child", "student"),
            ("admin", "other_admin"),
            ("parent", "parent_guardian"),
            ("outsider", "parent_guardian"),
        ):
            session.add(
                User(
                    id=ids[name],
                    school_id=ids["school"],
                    role=role,
                    first_name=name,
                    status="active",
                    auth_method="email_password",
                    date_of_birth=school_date if name == "child" else None,
                )
            )
        session.add(
            Class(
                id=ids["class"],
                school_id=ids["school"],
                name="P5 A",
                year_group="P5",
                academic_session="2026/2027",
            )
        )
        await session.flush()
        session.add(StudentClassEnrollment(student_id=ids["child"], class_id=ids["class"]))
        session.add(
            ParentLink(
                student_id=ids["child"],
                school_id=ids["school"],
                parent_id=ids["parent"],
                parent_name="Parent",
                parent_contact=f"{uuid4().hex}@example.com",
                contact_method="email",
                account_created=True,
            )
        )
    return engine, sessions, ids, school_date


async def app_for(sessions, ids):
    app = FastAPI()
    app.include_router(router)
    actor = {"name": "admin"}

    async def principal():
        name = actor["name"]
        return SimpleNamespace(
            user_id=ids[name], role="other_admin" if name == "admin" else "parent_guardian"
        )

    async def database():
        async with sessions() as session:
            yield session

    app.dependency_overrides[authenticated_principal] = principal
    app.dependency_overrides[database_session] = database
    return app, actor


@pytest.mark.skipif(not URL, reason="Disposable database required")
def test_hold_recheck_parent_precedence_and_authorisation_over_http():
    async def scenario():
        engine, sessions, ids, school_date = await setup()
        parent_date = school_date.replace(month=2)
        now = datetime.now(UTC)
        async with sessions.begin() as session:
            await record_parent_date(
                session, school_id=ids["school"], student_id=ids["child"], born=parent_date, now=now
            )
            check = await session.scalar(
                select(AgeCheck).where(AgeCheck.student_id == ids["child"])
            )
            check_id, notified = check.id, check.school_notified_at
            student = await session.get(User, ids["child"])
            assert check.blocks_access and check.enrolled_age_band == "upper_primary"
            assert student.date_of_birth == parent_date
            assert student.retention_due_at == notified + timedelta(days=30)
        account = await SqlAlchemyUserRepository(sessions).find_by_id(ids["child"])
        assert account.status == "pending"
        app, actor = await app_for(sessions, ids)
        base = f"/api/v1/age-checks/{check_id}"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            actor["name"] = "parent"
            response = await client.post(
                base + "/parent-reconfirm", json={"dateOfBirth": str(parent_date)}
            )
            assert response.status_code == 409, response.text
            assert response.json()["detail"]["code"] == "school_recheck_required"
            actor["name"] = "outsider"
            assert (
                await client.post(
                    base + "/parent-reconfirm", json={"dateOfBirth": str(parent_date)}
                )
            ).status_code == 404
            actor["name"] = "admin"
            rejected = await client.post(
                base + "/school-recheck",
                json={"dateOfBirth": str(school_date), "identityDocument": "not accepted"},
            )
            assert rejected.status_code == 422
            response = await client.post(
                base + "/school-recheck", json={"dateOfBirth": str(school_date)}
            )
            assert response.status_code == 200, response.text
            assert response.json()["blocksAccess"] is True
            actor["name"] = "parent"
            response = await client.post(
                base + "/parent-reconfirm", json={"dateOfBirth": str(parent_date)}
            )
            assert response.status_code == 200, response.text
            assert response.json()["state"] == "resolved" and not response.json()["blocksAccess"]
            assert response.json()["deletionDueAt"] is None
        async with sessions() as session:
            student = await session.get(User, ids["child"])
            assert student.date_of_birth == parent_date
            assert student.retention_due_at is None
            check = await session.get(AgeCheck, check_id)
            assert check.resolved_by_user_id == ids["parent"]
            assert check.school_rechecked_by == ids["admin"]
            assert check.school_notified_at == notified
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.recipient_id == ids["admin"])
                )
                == 1
            )
        assert (
            await SqlAlchemyUserRepository(sessions).find_by_id(ids["child"])
        ).status == "active"
        async with sessions.begin() as session:
            child = await session.get(User, ids["child"])
            child.date_of_birth = school_date
            await reconcile_school_date(session, child.id, school_date)
            await session.flush()
            await session.refresh(child)
            assert child.date_of_birth == parent_date
            assert not (await session.get(AgeCheck, check_id)).blocks_access
        await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(not URL, reason="Disposable database required")
@pytest.mark.parametrize("severe", ["gap", "outside_band", "missing_band"])
def test_hard_exceptions_cannot_be_approved(severe):
    async def scenario():
        engine, sessions, ids, school_date = await setup()
        parent_date = school_date.replace(year=school_date.year + (3 if severe == "gap" else 1))
        async with sessions.begin() as session:
            if severe == "outside_band":
                school_date = school_date.replace(year=school_date.year - 2)
                (await session.get(User, ids["child"])).date_of_birth = school_date
            if severe == "missing_band":
                (await session.get(Class, ids["class"])).year_group = "Unknown"
            await session.flush()
            await record_parent_date(
                session,
                school_id=ids["school"],
                student_id=ids["child"],
                born=parent_date,
                now=datetime.now(UTC),
            )
            check = await session.scalar(
                select(AgeCheck).where(AgeCheck.student_id == ids["child"])
            )
            check_id = check.id
        app, actor = await app_for(sessions, ids)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            base = f"/api/v1/age-checks/{check_id}"
            assert (
                await client.post(base + "/school-recheck", json={"dateOfBirth": str(school_date)})
            ).status_code == 200
            actor["name"] = "parent"
            response = await client.post(
                base + "/parent-reconfirm", json={"dateOfBirth": str(parent_date)}
            )
            assert response.status_code == 200, response.text
            assert response.json()["blocksAccess"]
            code = {
                "gap": "date_gap_exceeds_two_years",
                "outside_band": "outside_enrolled_age_band",
                "missing_band": "enrolled_age_band_unavailable",
            }[severe]
            assert code in response.json()["holdReasons"]
        await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(not URL, reason="Disposable database required")
def test_thirty_day_purge_deletes_signals_and_retries_storage_failure():
    async def scenario():
        engine, sessions, ids, school_date = await setup()
        now = datetime.now(UTC)
        async with sessions.begin() as session:
            session.add(
                SignalEvent(
                    student_id=ids["child"],
                    session_id=uuid4(),
                    event_type="scroll",
                    event_data={"depthRatio": 0.5},
                )
            )
            await record_parent_date(
                session,
                school_id=ids["school"],
                student_id=ids["child"],
                born=school_date.replace(month=2),
                now=now,
            )
            check = await session.scalar(
                select(AgeCheck).where(AgeCheck.student_id == ids["child"])
            )
            check_id = check.id
            # Notification age, not creation age, decides eligibility.
            check.created_at = now - timedelta(days=100)
        service = RetentionService(sessions, storage=Storage(), receipt_key="test-only")
        assert not await service._purge(ids["child"], now + timedelta(days=29))
        async with sessions.begin() as session:
            check = await session.get(AgeCheck, check_id)
            check.school_notified_at = now - timedelta(days=31)
        service._storage = Storage(fail=True)
        with pytest.raises(RuntimeError):
            await service._purge(ids["child"], now)
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(SignalEvent)
                    .where(SignalEvent.student_id == ids["child"])
                )
                == 1
            )
        service._storage = Storage()
        assert await service._purge(ids["child"], now)
        async with sessions() as session:
            child = await session.get(User, ids["child"])
            assert child.school_id is None and child.date_of_birth is None
            assert child.retention_purged_at is not None
            for model in (SignalEvent, StudentClassEnrollment, ParentLink, AgeCheck):
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.student_id == ids["child"])
                    )
                    == 0
                )
        assert not await service._purge(ids["child"], now)
        await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(not URL, reason="Disposable database required")
def test_existing_bearer_sessions_and_new_sessions_refused_while_held():
    async def scenario():
        engine, sessions, ids, school_date = await setup()
        service = build_auth_service(
            sessions,
            AuthSettings(
                _env_file=None,
                auth_password_pepper="p" * 40,
                auth_pin_pepper="i" * 40,
                auth_session_pepper="s" * 40,
            ),
        )
        issued = await service.issue_for_provisioned_user(ids["child"])
        app = FastAPI()
        app.state.auth_service = service
        app.include_router(auth_router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {issued.access_token}"}
            assert (await client.get("/api/v1/auth/session", headers=headers)).status_code == 200
            async with sessions.begin() as session:
                await record_parent_date(
                    session,
                    school_id=ids["school"],
                    student_id=ids["child"],
                    born=school_date.replace(month=2),
                    now=datetime.now(UTC),
                )
            response = await client.get("/api/v1/auth/session", headers=headers)
            assert response.status_code == 401, response.text
            assert response.json()["detail"]["code"] == "account_paused"
            from nevo.auth.errors import AccountPausedError

            with pytest.raises(AccountPausedError):
                await service.issue_for_provisioned_user(ids["child"])
        await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(not URL, reason="Disposable database required")
def test_no_deletion_clock_before_school_notification_and_expired_recheck_refused():
    async def scenario():
        engine, sessions, ids, school_date = await setup()
        now = datetime.now(UTC)
        async with sessions.begin() as session:
            admin = await session.get(User, ids["admin"])
            admin.status, admin.deactivated_at = "deactivated", now
            await session.flush()
            await record_parent_date(
                session,
                school_id=ids["school"],
                student_id=ids["child"],
                born=school_date.replace(month=2),
                now=now,
            )
            check = await session.scalar(
                select(AgeCheck).where(AgeCheck.student_id == ids["child"])
            )
            check_id = check.id
            assert check.blocks_access and check.school_notified_at is None
            assert (await session.get(User, ids["child"])).retention_due_at is None
        async with sessions.begin() as session:
            admin = await session.get(User, ids["admin"])
            admin.status, admin.deactivated_at = "active", None
        await prepare_pending_holds(sessions, now)
        await prepare_pending_holds(sessions, now + timedelta(days=1))
        async with sessions.begin() as session:
            check = await session.get(AgeCheck, check_id)
            assert check.school_notified_at == now
            assert (await session.get(User, ids["child"])).retention_due_at == now + timedelta(
                days=30
            )
            check.school_notified_at = now - timedelta(days=30)
        app, _actor = await app_for(sessions, ids)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/age-checks/{check_id}/school-recheck",
                json={"dateOfBirth": str(school_date)},
            )
            assert response.status_code == 410, response.text
        await engine.dispose()

    asyncio.run(scenario())
