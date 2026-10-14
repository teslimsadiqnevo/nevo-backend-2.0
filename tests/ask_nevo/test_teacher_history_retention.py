from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nevo.ask_nevo.repositories import SqlAlchemyAskNevoRepository, _teacher_thread_expired
from nevo.domain.ask_nevo.vocabulary import AskNevoRole
from nevo.retention.service import RetentionService


@pytest.mark.parametrize("days,expired", [(89, False), (90, True), (91, True)])
def test_teacher_history_expires_at_ninety_days(days, expired):
    now = datetime(2026, 10, 14, tzinfo=UTC)
    thread = SimpleNamespace(role=AskNevoRole.TEACHER, created_at=now - timedelta(days=days))
    assert _teacher_thread_expired(thread, now=now) is expired


def test_student_history_keeps_its_separate_school_retention_policy():
    thread = SimpleNamespace(role=AskNevoRole.STUDENT, created_at=datetime(2025, 1, 1))
    assert _teacher_thread_expired(thread) is False


@pytest.mark.asyncio
async def test_expired_teacher_transcript_cannot_be_read_before_the_sweep():
    actor_id = uuid4()
    thread = SimpleNamespace(
        role=AskNevoRole.TEACHER,
        created_at=datetime.now(UTC) - timedelta(days=91),
        actor_user_id=actor_id,
        deleted_at=None,
    )
    session = SimpleNamespace(get=AsyncMock(return_value=thread), scalars=AsyncMock())
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    repository = SqlAlchemyAskNevoRepository(lambda: context)
    assert await repository.read_thread(actor_user_id=actor_id, thread_id=uuid4()) is None
    session.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_daily_sweep_drains_every_expired_batch(monkeypatch):
    service = RetentionService(None)
    batch = AsyncMock(side_effect=[200, 3])
    monkeypatch.setattr(service, "_sweep_chat_batch", batch)
    assert await service._sweep_chats(datetime.now(UTC)) == 203
    assert batch.await_count == 2
