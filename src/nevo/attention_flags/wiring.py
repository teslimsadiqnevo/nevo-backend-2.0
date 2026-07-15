from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.service import AiGatewayService
from nevo.attention_flags.service import (
    AttentionFlagDetectionService,
    SqlAlchemyAttentionFlagRepository,
)


def build_attention_flag_detection_service(
    sessions: async_sessionmaker[AsyncSession],
    gateway: AiGatewayService,
) -> AttentionFlagDetectionService:
    return AttentionFlagDetectionService(
        repository=SqlAlchemyAttentionFlagRepository(sessions),
        gateway=gateway,
    )
