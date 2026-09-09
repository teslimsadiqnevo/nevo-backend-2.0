"""Ask Nevo conversations against real Postgres, inside a rolled-back txn."""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from nevo.ask_nevo.repositories import SqlAlchemyAskNevoRepository
from nevo.core.config import get_settings
from nevo.db.models.account import School, User
from nevo.db.models.ask_nevo import AskNevoThread
from nevo.db.session import create_engine
from nevo.domain.accounts.vocabulary import AuthMethod, UserRole, UserStatus
from nevo.domain.ask_nevo.vocabulary import AskNevoMessageAuthor, AskNevoRole
from nevo.retention.service import RetentionService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
    ),
]


async def with_world(check):  # type: ignore[no-untyped-def]
    engine = create_engine(get_settings().database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        sessions = async_sessionmaker(bind=connection, expire_on_commit=False)
        async with sessions() as setup:
            token = uuid.uuid4().hex[:12]
            school = School(
                name="Chat Test School",
                school_code=f"chat-{token}",
                school_url_slug=f"chat-{token}",
                data_retention_days=30,
            )
            setup.add(school)
            await setup.flush()
            asker = User(
                school_id=school.id,
                role=UserRole.STUDENT,
                auth_method=AuthMethod.PIN,
                status=UserStatus.ACTIVE,
            )
            other = User(
                school_id=school.id,
                role=UserRole.TEACHER,
                auth_method=AuthMethod.PIN,
                status=UserStatus.ACTIVE,
            )
            setup.add_all([asker, other])
            await setup.flush()
        return await check(sessions, asker, other)
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


async def test_a_conversation_is_stored_and_reads_back_in_order() -> None:
    async def check(sessions, asker, other):  # type: ignore[no-untyped-def]
        repo = SqlAlchemyAskNevoRepository(sessions)
        thread_id = uuid.uuid4()
        for question, answer in (
            ("What are fractions?", "A fraction is a part of a whole."),
            ("Can you say that more simply?", "It is a piece of something."),
        ):
            await repo.append_exchange(
                thread_id=thread_id,
                actor_user_id=asker.id,
                role=AskNevoRole.STUDENT,
                question=question,
                answer=answer,
                blocks=[{"type": "paragraph", "text": answer, "items": []}],
                interaction_id=None,
            )
        return await repo.read_thread(actor_user_id=asker.id, thread_id=thread_id)

    transcript = await with_world(check)

    assert transcript is not None
    assert transcript.title == "What are fractions?"
    assert [item.sequence for item in transcript.messages] == [1, 2, 3, 4]
    assert [item.author for item in transcript.messages] == [
        AskNevoMessageAuthor.ASKER,
        AskNevoMessageAuthor.NEVO,
        AskNevoMessageAuthor.ASKER,
        AskNevoMessageAuthor.NEVO,
    ]
    assert transcript.messages[3].body == "It is a piece of something."
    assert transcript.messages[3].blocks[0]["type"] == "paragraph"


async def test_nobody_else_can_read_a_learners_chat() -> None:
    """Not their teacher, not an administrator. It is the learner's own."""

    async def check(sessions, asker, other):  # type: ignore[no-untyped-def]
        repo = SqlAlchemyAskNevoRepository(sessions)
        thread_id = uuid.uuid4()
        await repo.append_exchange(
            thread_id=thread_id,
            actor_user_id=asker.id,
            role=AskNevoRole.STUDENT,
            question="Why do I keep getting this wrong?",
            answer="Let us look at it together.",
            blocks=[],
            interaction_id=None,
        )
        return (
            await repo.read_thread(actor_user_id=other.id, thread_id=thread_id),
            await repo.list_threads(actor_user_id=other.id),
        )

    transcript, listed = await with_world(check)

    assert transcript is None
    assert listed == []


async def test_a_deleted_chat_stops_being_readable() -> None:
    async def check(sessions, asker, other):  # type: ignore[no-untyped-def]
        repo = SqlAlchemyAskNevoRepository(sessions)
        thread_id = uuid.uuid4()
        await repo.append_exchange(
            thread_id=thread_id,
            actor_user_id=asker.id,
            role=AskNevoRole.STUDENT,
            question="Something private",
            answer="An answer",
            blocks=[],
            interaction_id=None,
        )
        removed = await repo.delete_thread(actor_user_id=asker.id, thread_id=thread_id)
        return (
            removed,
            await repo.read_thread(actor_user_id=asker.id, thread_id=thread_id),
            await repo.list_threads(actor_user_id=asker.id),
            await repo.delete_thread(actor_user_id=asker.id, thread_id=thread_id),
        )

    removed, transcript, listed, repeated = await with_world(check)

    assert removed is True
    assert transcript is None
    assert listed == []
    assert repeated is False


async def test_a_chat_past_its_school_window_is_swept_away() -> None:
    """A child's own words expire on the same clock as everything else."""

    async def check(sessions, asker, other):  # type: ignore[no-untyped-def]
        repo = SqlAlchemyAskNevoRepository(sessions)
        fresh, stale = uuid.uuid4(), uuid.uuid4()
        for thread_id in (fresh, stale):
            await repo.append_exchange(
                thread_id=thread_id,
                actor_user_id=asker.id,
                role=AskNevoRole.STUDENT,
                question=f"Question {thread_id}",
                answer="An answer",
                blocks=[],
                interaction_id=None,
            )
        async with sessions.begin() as session:
            row = await session.get(AskNevoThread, stale)
            row.last_message_at = datetime.now(UTC) - timedelta(days=90)

        result = await RetentionService(sessions).sweep()

        async with sessions() as session:
            surviving = set(
                await session.scalars(
                    select(AskNevoThread.id).where(
                        AskNevoThread.actor_user_id == asker.id
                    )
                )
            )
        return result, fresh, stale, surviving

    result, fresh, stale, surviving = await with_world(check)

    assert result.chats_removed >= 1
    assert fresh in surviving
    assert stale not in surviving
