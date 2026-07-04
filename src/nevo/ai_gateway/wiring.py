from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy
from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.fallback import RuleBasedFallbackGenerator
from nevo.ai_gateway.gemini import GeminiRestProvider
from nevo.ai_gateway.prompts import PromptRenderer
from nevo.ai_gateway.repositories import (
    SqlAlchemyAiCallRepository,
    SqlAlchemyPromptTemplateRepository,
)
from nevo.ai_gateway.scheduler import PriorityRateLimitedScheduler
from nevo.ai_gateway.service import AiGatewayService


def build_ai_gateway(
    sessions: async_sessionmaker[AsyncSession],
    settings: AiGatewaySettings,
) -> AiGatewayService:
    compliance = ZeroTagCompliancePolicy()
    api_key = (
        settings.gemini_api_key.get_secret_value()
        if settings.gemini_api_key is not None
        else None
    )
    return AiGatewayService(
        prompts=SqlAlchemyPromptTemplateRepository(sessions),
        calls=SqlAlchemyAiCallRepository(sessions),
        provider=GeminiRestProvider(
            api_key=api_key,
            model=settings.gemini_model,
            base_url=str(settings.gemini_base_url),
            timeout_seconds=settings.request_timeout_seconds,
        ),
        fallback=RuleBasedFallbackGenerator(compliance),
        scheduler=PriorityRateLimitedScheduler(
            max_concurrency=settings.max_concurrency,
            requests_per_minute=settings.requests_per_minute,
        ),
        compliance=compliance,
        renderer=PromptRenderer(),
        max_compliance_retries=settings.max_compliance_retries,
        input_cost_usd_per_million=settings.input_cost_usd_per_million,
        output_cost_usd_per_million=settings.output_cost_usd_per_million,
    )
