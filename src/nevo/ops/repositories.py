from datetime import date
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.heartbeat import SystemHeartbeat
from nevo.ops.entities import HeartbeatRecord


class SqlAlchemyHeartbeatRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record(self, beat_date: date) -> HeartbeatRecord | None:
        async with self._sessions.begin() as session:
            statement = (
                insert(SystemHeartbeat)
                .values(id=uuid4(), beat_date=beat_date)
                .on_conflict_do_nothing(
                    index_elements=[SystemHeartbeat.beat_date]
                )
                .returning(SystemHeartbeat)
            )
            row = (await session.execute(statement)).scalar_one_or_none()
            if row is None:
                return None
            return HeartbeatRecord(
                id=row.id,
                beat_date=row.beat_date,
                created_at=row.created_at,
            )
