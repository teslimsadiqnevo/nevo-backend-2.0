from decimal import Decimal

from nevo.ai_gateway.claude import ClaudeRestProvider
from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.wiring import _provider_from_settings


def test_ai_gateway_defaults_to_claude_haiku_with_prompt_caching() -> None:
    settings = AiGatewaySettings()

    assert settings.provider == "claude"
    assert settings.anthropic_model == "claude-haiku-4-5"
    assert settings.anthropic_sonnet_model == "claude-sonnet-5"
    assert settings.prompt_caching_enabled is True
    assert settings.input_cost_usd_per_million == Decimal("1")
    assert settings.output_cost_usd_per_million == Decimal("5")
    assert settings.cache_write_cost_usd_per_million == Decimal("1.25")
    assert settings.cache_read_cost_usd_per_million == Decimal("0.10")


def test_ai_gateway_wiring_uses_claude_provider_by_default() -> None:
    provider = _provider_from_settings(AiGatewaySettings())

    assert isinstance(provider, ClaudeRestProvider)


def test_missing_key_is_reported_as_not_configured() -> None:
    """A missing key must not look like a provider outage.

    The two need different responses - set a variable versus wait for a
    provider - so they must not share an error code in the audit trail.
    """
    from nevo.ai_gateway.claude import ClaudeRestProvider
    from nevo.ai_gateway.errors import (
        ProviderNotConfiguredError,
        ProviderUnavailableError,
    )

    provider = ClaudeRestProvider(
        api_key=None,
        model="claude-haiku-4-5",
        base_url="https://api.anthropic.com/v1",
        anthropic_version="2023-06-01",
        timeout_seconds=5,
        prompt_caching_enabled=False,
    )

    assert not provider.configured
    assert ProviderNotConfiguredError.code == "provider_not_configured"
    # Still an unavailability, so existing handling keeps working.
    assert issubclass(ProviderNotConfiguredError, ProviderUnavailableError)


def test_a_configured_provider_reports_itself_configured() -> None:
    from nevo.ai_gateway.claude import ClaudeRestProvider

    provider = ClaudeRestProvider(
        api_key="sk-ant-test",
        model="claude-haiku-4-5",
        base_url="https://api.anthropic.com/v1",
        anthropic_version="2023-06-01",
        timeout_seconds=5,
        prompt_caching_enabled=False,
    )

    assert provider.configured


def test_the_default_sonnet_model_is_a_real_model_id() -> None:
    """`claude-sonnet` is not a valid id and would 404 the moment it is wired."""
    from nevo.ai_gateway.config import AiGatewaySettings

    # The class default, not a resolved instance: a deployment can still
    # override this with a bad value, which is exactly what had happened.
    fields = AiGatewaySettings.model_fields

    assert fields["anthropic_sonnet_model"].default == "claude-sonnet-5"
    assert fields["anthropic_model"].default == "claude-haiku-4-5"
