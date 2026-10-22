from sqlalchemy import case, func, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.signal_events.entities import SignalIngestionBatch
from nevo.signal_events.errors import SessionMismatchError


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
                session_type=session_snapshot.session_type,
                started_at=session_snapshot.started_at,
                ended_at=session_snapshot.ended_at,
                completion_status=session_snapshot.completion_status,
                exit_position=session_snapshot.exit_position,
                break_count=session_snapshot.break_count,
                proactive_adjustments_count=(session_snapshot.proactive_adjustments_count),
            )
            terminal = or_(
                LessonSession.completion_status == "completed",
                LessonSession.ended_at.is_not(None),
            )
            valid_end = case(
                (
                    statement.excluded.ended_at >= LessonSession.started_at,
                    statement.excluded.ended_at,
                ),
                else_=None,
            )
            updated = await session.scalar(
                statement.on_conflict_do_update(
                    index_elements=[LessonSession.id],
                    set_={
                        "ended_at": func.coalesce(LessonSession.ended_at, valid_end),
                        "lesson_id": func.coalesce(
                            LessonSession.lesson_id, statement.excluded.lesson_id
                        ),
                        "completion_status": case(
                            (terminal, LessonSession.completion_status),
                            else_=statement.excluded.completion_status,
                        ),
                        "exit_position": case(
                            (terminal, LessonSession.exit_position),
                            else_=func.coalesce(
                                statement.excluded.exit_position, LessonSession.exit_position
                            ),
                        ),
                        "break_count": func.greatest(
                            LessonSession.break_count, statement.excluded.break_count
                        ),
                        "proactive_adjustments_count": func.greatest(
                            LessonSession.proactive_adjustments_count,
                            statement.excluded.proactive_adjustments_count,
                        ),
                    },
                    where=(LessonSession.student_id == session_snapshot.student_id)
                    & or_(
                        LessonSession.lesson_id.is_(None),
                        statement.excluded.lesson_id.is_(None),
                        LessonSession.lesson_id == statement.excluded.lesson_id,
                    ),
                ).returning(LessonSession.id)
            )
            if updated is None:
                raise SessionMismatchError
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
