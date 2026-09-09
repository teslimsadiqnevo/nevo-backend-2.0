from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.consent.service import ConsentService
from nevo.parents.repositories import SqlAlchemyParentInsightRepository
from nevo.parents.service import ParentInsightService


def build_parent_insight_service(
    sessions: async_sessionmaker[AsyncSession],
    *,
    consent: ConsentService,
) -> ParentInsightService:
    return ParentInsightService(
        repository=SqlAlchemyParentInsightRepository(sessions),
        consent=consent,
    )
