from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.service import AiGatewayService
from nevo.intelligence.adaptation import (
    AdaptationEngineService,
    SqlAlchemyLearnerProfileRepository,
)


def build_adaptation_engine_service(
    sessions: async_sessionmaker[AsyncSession],
    gateway: AiGatewayService,
) -> AdaptationEngineService:
    return AdaptationEngineService(
        profiles=SqlAlchemyLearnerProfileRepository(sessions),
        gateway=gateway,
    )
