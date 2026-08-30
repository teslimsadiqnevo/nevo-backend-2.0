from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.claude import ClaudeRestProvider
from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy
from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.fallback import RuleBasedFallbackGenerator
from nevo.ai_gateway.ports import TextGenerationProvider
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
    return AiGatewayService(
        prompts=SqlAlchemyPromptTemplateRepository(sessions),
        calls=SqlAlchemyAiCallRepository(sessions),
        provider=_provider_from_settings(settings),
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
        cache_write_cost_usd_per_million=settings.cache_write_cost_usd_per_million,
        cache_read_cost_usd_per_million=settings.cache_read_cost_usd_per_million,
    )


def _provider_from_settings(settings: AiGatewaySettings) -> TextGenerationProvider:
    if settings.provider != "claude":
        raise ValueError("AI_PROVIDER must be 'claude'")
    return ClaudeRestProvider(
        api_key=(
            settings.anthropic_api_key.get_secret_value()
            if settings.anthropic_api_key is not None
            else None
        ),
        model=settings.anthropic_model,
        base_url=str(settings.anthropic_base_url),
        anthropic_version=settings.anthropic_version,
        timeout_seconds=settings.request_timeout_seconds,
        prompt_caching_enabled=settings.prompt_caching_enabled,
    )
