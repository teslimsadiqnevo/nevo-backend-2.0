from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.scheduler.repositories import SqlAlchemySchedulerRepository
from nevo.scheduler.service import FsrsSchedulerService


def build_scheduler_service(
    sessions: async_sessionmaker[AsyncSession],
) -> FsrsSchedulerService:
    return FsrsSchedulerService(SqlAlchemySchedulerRepository(sessions))
