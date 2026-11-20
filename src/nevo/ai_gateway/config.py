from decimal import Decimal
from typing import ClassVar, Literal

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
    safety_policy_v2_enabled: bool = Field(
        default=False, validation_alias="SAFETY_POLICY_V2_ENABLED"
    )
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
    #: Published per-million prices, by model. The settings below are the
    #: fallback for a model not named here.
    #:
    #: One flat price pair used to be applied to every model, and it was the
    #: cheapest model's: $1 in, $5 out, which is Haiku 4.5 exactly. Of 2,626
    #: recorded calls, 872 ran on Sonnet 5 and 11 on Sonnet 4.6, all of them
    #: billed at Haiku's rate - so the all-time figure read $9.97 when it was
    #: about $15.70. Lydia, 20 November: everything about pricing is blocked
    #: on the per-learner cost, so a number that understates by a third is
    #: worse than no number.
    #:
    #: Cache writes are 1.25x input and cache reads 0.1x input, which is why
    #: caching the document is worth doing at all.
    @property
    def prices_are_configured(self) -> bool:
        """Whether somebody set the prices deliberately.

        If they did, those win and the published table is not consulted: a
        negotiated rate must not be silently replaced by a list price. If
        they did not, the table applies, because one flat pair across every
        model is how Sonnet came to be billed at Haiku's rate.
        """
        return bool(
            {
                "input_cost_usd_per_million",
                "output_cost_usd_per_million",
                "cache_write_cost_usd_per_million",
                "cache_read_cost_usd_per_million",
            }
            & self.model_fields_set
        )

    MODEL_PRICES: ClassVar[dict[str, tuple[str, str, str, str]]] = {
        # model: (input, output, cache_write, cache_read) per million USD
        "claude-haiku-4-5": ("1", "5", "1.25", "0.10"),
        "claude-haiku-5-5": ("0.10", "0.50", "0.125", "0.01"),
        "claude-sonnet-4-6": ("3", "15", "3.75", "0.30"),
        "claude-sonnet-5": ("2", "10", "2.50", "0.20"),
        "claude-sonnet-5-5": ("2", "10", "2.50", "0.10"),
        "claude-opus-5": ("5", "25", "6.25", "0.50"),
        "claude-opus-5-5": ("4", "20", "5", "0.20"),
    }

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
