from decimal import Decimal
from typing import Literal

from pydantic import AnyHttpUrl, Field, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

AI_PROVIDER_CLAUDE = "claude"


class AiGatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: Literal["claude"] = AI_PROVIDER_CLAUDE
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-haiku-4-5"
    anthropic_sonnet_model: str = "claude-sonnet-5"
    anthropic_base_url: AnyHttpUrl = AnyHttpUrl("https://api.anthropic.com/v1")
    anthropic_version: str = "2023-06-01"
    prompt_caching_enabled: bool = True
    request_timeout_seconds: float = Field(default=20, gt=0, le=120)
    requests_per_minute: PositiveInt = 60
    max_concurrency: PositiveInt = 4
    max_compliance_retries: int = Field(default=2, ge=0, le=3)
    input_cost_usd_per_million: Decimal = Field(
        default=Decimal("1"),
        ge=0,
    )
    output_cost_usd_per_million: Decimal = Field(
        default=Decimal("5"),
        ge=0,
    )
    cache_write_cost_usd_per_million: Decimal = Field(
        default=Decimal("1.25"),
        ge=0,
    )
    cache_read_cost_usd_per_million: Decimal = Field(
        default=Decimal("0.10"),
        ge=0,
    )
