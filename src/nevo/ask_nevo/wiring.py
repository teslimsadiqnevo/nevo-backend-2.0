from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy
from nevo.ai_gateway.service import AiGatewayService
from nevo.ask_nevo.repositories import SqlAlchemyAskNevoRepository
from nevo.ask_nevo.service import AskNevoService


def build_ask_nevo_service(
    sessions: async_sessionmaker[AsyncSession],
    gateway: AiGatewayService,
) -> AskNevoService:
    return AskNevoService(
        repository=SqlAlchemyAskNevoRepository(sessions),
        gateway=gateway,
        compliance=ZeroTagCompliancePolicy(),
    )
