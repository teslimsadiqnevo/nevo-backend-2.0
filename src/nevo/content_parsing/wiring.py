from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.service import AiGatewayService
from nevo.content_parsing.repositories import SqlAlchemyContentParsingRepository
from nevo.content_parsing.service import ContentParsingService


def build_content_parsing_service(
    sessions: async_sessionmaker[AsyncSession],
    ai_gateway: AiGatewayService,
) -> ContentParsingService:
    return ContentParsingService(
        repository=SqlAlchemyContentParsingRepository(sessions),
        ai_gateway=ai_gateway,
    )
