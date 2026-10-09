from typing import ClassVar

from pydantic import Field, SecretStr
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
    #: A placeholder, deliberately. The real number lives in the deployed
    #: environment and nowhere else. SCRUM-205.
    #:
    #: Not because an account number is secret - it is printed on every
    #: invoice and goes to every school that pays. Two operational reasons.
    #: A wrong account number on a billing screen is the most expensive field
    #: in the product to get wrong, and while it sat in the repository
    #: changing it needed a deploy. And it makes the rule about never showing
    #: the real number outside the product mechanical rather than remembered:
    #: a demo or staging environment that has not been given the variable
    #: shows ten zeroes, which is obviously not an account to pay into.
    #:
    #: What a paying school sees is unchanged, still served from the endpoint
    #: in SCRUM-119.
    PLACEHOLDER_ACCOUNT_NUMBER: ClassVar[str] = "0000000000"

    account_number: str = Field(
        default=PLACEHOLDER_ACCOUNT_NUMBER,
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
    finance_confirmation_key: SecretStr | None = Field(
        default=None,
        validation_alias="BILLING_FINANCE_CONFIRMATION_KEY",
    )

    def details(self) -> BankTransferDetails:
        return BankTransferDetails(
            bank_name=self.bank_name,
            account_number=self.account_number,
            account_name=self.account_name,
            currency=self.currency,
        )
