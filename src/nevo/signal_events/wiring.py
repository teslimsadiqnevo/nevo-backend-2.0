from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.signal_events.repositories import SqlAlchemySignalIngestionRepository
from nevo.signal_events.service import SignalIngestionService


def build_signal_ingestion_service(
    sessions: async_sessionmaker[AsyncSession],
) -> SignalIngestionService:
    return SignalIngestionService(
        repository=SqlAlchemySignalIngestionRepository(sessions),
    )
