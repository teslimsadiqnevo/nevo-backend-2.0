from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.service import AiGatewayService
from nevo.intelligence.accommodation_repositories import (
    SqlAlchemyAccommodationPatternRepository,
)
from nevo.intelligence.accommodation_service import AccommodationInferenceService
from nevo.intelligence.accommodations import UdlAccommodationInferenceEngine
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


def build_accommodation_inference_service(
    sessions: async_sessionmaker[AsyncSession],
) -> AccommodationInferenceService:
    return AccommodationInferenceService(
        repository=SqlAlchemyAccommodationPatternRepository(sessions),
        engine=UdlAccommodationInferenceEngine(),
    )
