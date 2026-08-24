from decimal import Decimal

from nevo.ai_gateway.claude import ClaudeRestProvider
from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.wiring import _provider_from_settings


def test_ai_gateway_defaults_to_claude_haiku_with_prompt_caching() -> None:
    settings = AiGatewaySettings()

    assert settings.provider == "claude"
    assert settings.anthropic_model == "claude-haiku-4-5"
    assert settings.anthropic_sonnet_model == "claude-sonnet"
    assert settings.prompt_caching_enabled is True
    assert settings.input_cost_usd_per_million == Decimal("1")
    assert settings.output_cost_usd_per_million == Decimal("5")
    assert settings.cache_write_cost_usd_per_million == Decimal("1.25")
    assert settings.cache_read_cost_usd_per_million == Decimal("0.10")


def test_ai_gateway_wiring_uses_claude_provider_by_default() -> None:
    provider = _provider_from_settings(AiGatewaySettings())

    assert isinstance(provider, ClaudeRestProvider)
