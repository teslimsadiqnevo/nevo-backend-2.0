from decimal import Decimal

from pydantic import AnyHttpUrl, Field, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AiGatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: AnyHttpUrl = AnyHttpUrl(
        "https://generativelanguage.googleapis.com/v1beta"
    )
    request_timeout_seconds: float = Field(default=20, gt=0, le=120)
    requests_per_minute: PositiveInt = 60
    max_concurrency: PositiveInt = 4
    max_compliance_retries: int = Field(default=2, ge=0, le=3)
    input_cost_usd_per_million: Decimal = Field(
        default=Decimal("0"),
        ge=0,
    )
    output_cost_usd_per_million: Decimal = Field(
        default=Decimal("0"),
        ge=0,
    )
