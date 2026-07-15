from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.service import AiGatewayService
from nevo.learner_profiles.profile_updates import (
    PostLessonProfileUpdateService,
    SqlAlchemyPostLessonProfileUpdateRepository,
)


def build_post_lesson_profile_update_service(
    sessions: async_sessionmaker[AsyncSession],
    gateway: AiGatewayService,
) -> PostLessonProfileUpdateService:
    return PostLessonProfileUpdateService(
        repository=SqlAlchemyPostLessonProfileUpdateRepository(sessions),
        gateway=gateway,
    )
