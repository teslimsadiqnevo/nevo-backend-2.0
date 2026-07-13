from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nevo.domain.signal_events.vocabulary import (
    LessonCompletionStatus,
    SignalEventType,
)
from nevo.signal_events.entities import (
    LessonSessionSnapshot,
    SignalEventDraft,
    SignalIngestionBatch,
)
from nevo.signal_events.errors import EmptySignalBatchError, SessionMismatchError
from nevo.signal_events.service import SignalIngestionService

from .fakes import MemorySignalIngestionRepository


def batch_with_events(*events: SignalEventDraft) -> SignalIngestionBatch:
    session_id = events[0].session_id if events else uuid4()
    student_id = events[0].student_id if events else uuid4()
    return SignalIngestionBatch(
        session=LessonSessionSnapshot(
            id=session_id,
            student_id=student_id,
            lesson_id=uuid4(),
            started_at=datetime(2026, 7, 13, 12, tzinfo=UTC),
            ended_at=None,
            completion_status=LessonCompletionStatus.IN_PROGRESS,
            exit_position=None,
            break_count=0,
            proactive_adjustments_count=0,
        ),
        events=events,
    )


def signal_event(
    *,
    session_id,
    student_id,
    event_type: SignalEventType = SignalEventType.SCROLL,
) -> SignalEventDraft:
    return SignalEventDraft(
        student_id=student_id,
        session_id=session_id,
        event_type=event_type,
        event_data={},
        timestamp=datetime(2026, 7, 13, 12, 1, tzinfo=UTC),
    )


async def test_service_persists_valid_batch() -> None:
    repository = MemorySignalIngestionRepository()
    service = SignalIngestionService(repository)
    session_id = uuid4()
    student_id = uuid4()

    receipt = await service.ingest(
        batch_with_events(
            signal_event(session_id=session_id, student_id=student_id)
        )
    )

    assert receipt.session_id == session_id
    assert receipt.accepted_events == 1
    assert len(repository.batches) == 1


async def test_service_rejects_empty_batch() -> None:
    service = SignalIngestionService(MemorySignalIngestionRepository())

    with pytest.raises(EmptySignalBatchError):
        await service.ingest(batch_with_events())


async def test_service_rejects_mixed_session_batch() -> None:
    service = SignalIngestionService(MemorySignalIngestionRepository())
    student_id = uuid4()

    with pytest.raises(SessionMismatchError):
        await service.ingest(
            batch_with_events(
                signal_event(session_id=uuid4(), student_id=student_id),
                signal_event(session_id=uuid4(), student_id=student_id),
            )
        )
