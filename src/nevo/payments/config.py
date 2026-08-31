from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from nevo.domain.billing.vocabulary import PricingCurrency


class PaystackSettings(BaseSettings):
    """Paystack processor configuration.

    Only ``PAYSTACK_SECRET_KEY`` is required to switch payments on; everything
    else has a working default.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    secret_key: SecretStr | None = Field(default=None, validation_alias="PAYSTACK_SECRET_KEY")
    base_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("https://api.paystack.co"),
        validation_alias="PAYSTACK_BASE_URL",
    )
    callback_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("http://localhost:3000/billing/payment-complete"),
        validation_alias="PAYSTACK_CALLBACK_URL",
    )
    currency: PricingCurrency = Field(
        default=PricingCurrency.NGN,
        validation_alias="PAYSTACK_CURRENCY",
    )
    auto_charge_enabled: bool = Field(
        default=True,
        validation_alias="PAYSTACK_AUTO_CHARGE_ENABLED",
    )
