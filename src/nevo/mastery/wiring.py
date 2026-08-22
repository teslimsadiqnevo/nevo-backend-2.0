from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.mastery.engine import HybridAktMasteryEngine
from nevo.mastery.repositories import SqlAlchemyMasteryRepository
from nevo.mastery.service import MasteryService


def build_mastery_service(
    sessions: async_sessionmaker[AsyncSession],
) -> MasteryService:
    return MasteryService(
        repository=SqlAlchemyMasteryRepository(sessions),
        engine=HybridAktMasteryEngine(),
    )
