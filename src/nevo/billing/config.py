from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from nevo.billing.entities import BankTransferDetails
from nevo.domain.billing.vocabulary import PricingCurrency


class BankTransferSettings(BaseSettings):
    """Nevo's own receiving account, served rather than hardcoded in clients.

    Environment-overridable so the account can be changed in one place. A
    wrong number here sends a school's fees to a stranger, so it is worth
    keeping out of every frontend that renders a payment panel.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    bank_name: str = Field(default="Kuda Bank", validation_alias="BILLING_BANK_NAME")
    account_number: str = Field(
        default="3004167012",
        validation_alias="BILLING_BANK_ACCOUNT_NUMBER",
    )
    account_name: str = Field(
        default="Nevo Learning Limited",
        validation_alias="BILLING_BANK_ACCOUNT_NAME",
    )
    currency: PricingCurrency = Field(
        default=PricingCurrency.NGN,
        validation_alias="BILLING_BANK_CURRENCY",
    )

    def details(self) -> BankTransferDetails:
        return BankTransferDetails(
            bank_name=self.bank_name,
            account_number=self.account_number,
            account_name=self.account_name,
            currency=self.currency,
        )
