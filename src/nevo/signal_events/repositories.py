from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.signal_events.entities import SignalIngestionBatch


class SqlAlchemySignalIngestionRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def ingest(self, batch: SignalIngestionBatch) -> None:
        session_snapshot = batch.session
        async with self._sessions.begin() as session:
            statement = insert(LessonSession).values(
                id=session_snapshot.id,
                student_id=session_snapshot.student_id,
                lesson_id=session_snapshot.lesson_id,
                started_at=session_snapshot.started_at,
                ended_at=session_snapshot.ended_at,
                completion_status=session_snapshot.completion_status,
                exit_position=session_snapshot.exit_position,
                break_count=session_snapshot.break_count,
                proactive_adjustments_count=(
                    session_snapshot.proactive_adjustments_count
                ),
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[LessonSession.id],
                    set_={
                        "ended_at": statement.excluded.ended_at,
                        "completion_status": statement.excluded.completion_status,
                        "exit_position": statement.excluded.exit_position,
                        "break_count": statement.excluded.break_count,
                        "proactive_adjustments_count": (
                            statement.excluded.proactive_adjustments_count
                        ),
                    },
                )
            )
            await session.execute(
                insert(SignalEvent),
                [
                    {
                        "student_id": event.student_id,
                        "session_id": event.session_id,
                        "event_type": event.event_type,
                        "event_data": event.event_data,
                        "timestamp": event.timestamp,
                    }
                    for event in batch.events
                ],
            )
