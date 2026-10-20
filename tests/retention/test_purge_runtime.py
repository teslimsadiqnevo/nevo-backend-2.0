"""Exercise real erasure and database guards only on a disposable database."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nevo.db.models.account import School, User
from nevo.db.models.frontend_support import Notification
from nevo.db.models.learner_profile import LearnerProfile, LearnerProfileHistory
from nevo.db.models.retention import LearnerPurgeReceipt
from nevo.db.models.signal_event import SignalEvent
from nevo.retention.service import RetentionService

URL = os.getenv("NEVO_RUNTIME_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="Disposable database required")


class Storage:
    configured = True

    def __init__(self, fail=False):
        self.fail = fail
        self.deleted = []

    async def list_paths(self, prefix):
        return [prefix + "/proof.pdf"]

    async def delete(self, path):
        if self.fail:
            raise RuntimeError("Storage unavailable")
        self.deleted.append(path)


@pytest.mark.parametrize("fail_first", [False, True])
def test_real_purge_is_isolated_retryable_and_cannot_be_recreated(fail_first):
    async def scenario():
        parsed = make_url(URL)
        assert parsed.host in {"127.0.0.1", "localhost"}
        assert parsed.database == "nevo_adaptation_tests"
        engine = create_async_engine(URL, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        school_id, child_id, other_id = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        async with sessions.begin() as session:
            session.add(
                School(
                    id=school_id,
                    name="Purge test",
                    school_code=uuid4().hex[:8],
                    school_url_slug=uuid4().hex,
                    auth_method="email_password",
                )
            )
            await session.flush()
            session.add_all(
                [
                    User(
                        id=child_id,
                        school_id=school_id,
                        role="student",
                        auth_method="pin",
                        first_name="Erasure",
                        last_name="Example",
                        email=f"{uuid4().hex}@example.com",
                        status="deactivated",
                        deactivated_at=now - timedelta(days=200),
                    ),
                    User(
                        id=other_id,
                        school_id=school_id,
                        role="student",
                        auth_method="pin",
                        first_name="Other",
                        status="active",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    SignalEvent(
                        student_id=child_id,
                        session_id=uuid4(),
                        event_type="time_on_segment",
                        event_data={"duration": 30},
                    ),
                    SignalEvent(
                        student_id=other_id,
                        session_id=uuid4(),
                        event_type="time_on_segment",
                        event_data={"duration": 20},
                    ),
                ]
            )
            profile = LearnerProfile(id=uuid4(), learner_id=child_id)
            session.add(profile)
            await session.flush()
            session.add(
                LearnerProfileHistory(
                    learner_profile_id=profile.id,
                    learner_id=child_id,
                    version=1,
                    observed_event_count=1,
                    change_source="system_inference",
                )
            )
            session.add_all(
                [
                    Notification(
                        recipient_id=child_id,
                        recipient_role="student",
                        type="test",
                        title="Private",
                        description="Progress",
                        read=False,
                    ),
                    Notification(
                        recipient_id=other_id,
                        recipient_role="student",
                        type="test",
                        title="Other",
                        description="Other progress",
                        read=False,
                    ),
                ]
            )
        storage = Storage(fail_first)
        with pytest.raises(DBAPIError, match="append-only"):
            async with sessions.begin() as session:
                await session.execute(delete(SignalEvent).where(SignalEvent.student_id == child_id))
        with pytest.raises(DBAPIError, match="immutable"):
            async with sessions.begin() as session:
                await session.execute(
                    delete(LearnerProfileHistory).where(
                        LearnerProfileHistory.learner_id == child_id
                    )
                )
        service = RetentionService(sessions, storage=storage, receipt_key="test-audit-key")
        if fail_first:
            result = await service.sweep(now=now)
            assert result.failed >= 1
            async with sessions() as session:
                assert (await session.get(User, child_id)).retention_purged_at is None
                receipt = await session.scalar(
                    select(LearnerPurgeReceipt).where(LearnerPurgeReceipt.student_id == child_id)
                )
                assert receipt.status == "retry"
            storage.fail = False
        result = await service.sweep(now=now)
        assert result.anonymised >= 1
        async with sessions() as session:
            child = await session.get(User, child_id)
            assert child.retention_purged_at is not None
            assert child.school_id is None and child.email is None
            assert child.preferences == {} and child.baseline_profile == {}
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(LearnerProfileHistory)
                    .where(LearnerProfileHistory.learner_id == child_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(LearnerProfile)
                    .where(LearnerProfile.learner_id == child_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(SignalEvent)
                    .where(SignalEvent.student_id == child_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(SignalEvent)
                    .where(SignalEvent.student_id == other_id)
                )
                == 1
            )
            assert (await session.get(User, other_id)).first_name == "Other"
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.recipient_id == child_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.recipient_id == other_id)
                )
                == 1
            )
        assert len(storage.deleted) >= 2
        with pytest.raises(IntegrityError, match="learner_retention_purged"):
            async with sessions.begin() as session:
                session.add(
                    Notification(
                        recipient_id=child_id,
                        recipient_role="student",
                        type="test",
                        title="Late write",
                        description="Must not persist",
                        read=False,
                    )
                )
        assert (await service.sweep(now=now)).anonymised == 0
        await engine.dispose()

    asyncio.run(scenario())
