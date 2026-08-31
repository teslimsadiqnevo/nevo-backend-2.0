import hashlib
import hmac
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

from nevo.domain.billing.vocabulary import (
    PaymentMethodType,
    PaymentTransactionStatus,
    PricingCurrency,
)
from nevo.payments.config import PaystackSettings
from nevo.payments.entities import ProviderAuthorization, ProviderTransaction
from nevo.payments.errors import (
    PaymentProviderRejectedError,
    PaymentProviderUnavailableError,
)

STATUS_BY_PROVIDER_VALUE = {
    "success": PaymentTransactionStatus.SUCCESS,
    "failed": PaymentTransactionStatus.FAILED,
    "abandoned": PaymentTransactionStatus.ABANDONED,
    "reversed": PaymentTransactionStatus.FAILED,
    "pending": PaymentTransactionStatus.PENDING,
    "ongoing": PaymentTransactionStatus.PENDING,
    "queued": PaymentTransactionStatus.PENDING,
}


def to_minor_units(amount: Decimal) -> int:
    """Paystack prices in the currency subunit (kobo, cents, pence)."""
    return int(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def from_minor_units(amount_minor: int) -> Decimal:
    return (Decimal(amount_minor) / Decimal("100")).quantize(Decimal("0.01"))


def verify_webhook_signature(*, payload: bytes, signature: str | None, secret: str) -> bool:
    """Paystack signs the raw body with HMAC-SHA512 keyed on the secret key."""
    if not signature:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


class PaystackClient:
    def __init__(self, settings: PaystackSettings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        return self._settings.secret_key is not None

    @property
    def currency(self) -> PricingCurrency:
        return self._settings.currency

    def secret(self) -> str:
        key = self._settings.secret_key
        if key is None:
            raise PaymentProviderUnavailableError
        return key.get_secret_value()

    async def initialize_transaction(
        self,
        *,
        email: str,
        amount: Decimal,
        reference: str,
        currency: PricingCurrency,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a checkout and return the hosted authorization URL."""
        body = await self._post(
            "/transaction/initialize",
            {
                "email": email,
                "amount": to_minor_units(amount),
                "reference": reference,
                "currency": currency.value,
                "callback_url": str(self._settings.callback_url),
                "metadata": metadata or {},
            },
        )
        url = body.get("authorization_url")
        if not isinstance(url, str) or not url:
            raise PaymentProviderRejectedError("Paystack returned no authorization URL")
        return url

    async def verify_transaction(self, reference: str) -> ProviderTransaction:
        body = await self._get(f"/transaction/verify/{reference}")
        return _parse_transaction(body)

    async def charge_authorization(
        self,
        *,
        email: str,
        amount: Decimal,
        reference: str,
        authorization_code: str,
        currency: PricingCurrency,
    ) -> ProviderTransaction:
        """Charge a stored authorization without the payer being present."""
        body = await self._post(
            "/transaction/charge_authorization",
            {
                "email": email,
                "amount": to_minor_units(amount),
                "reference": reference,
                "authorization_code": authorization_code,
                "currency": currency.value,
            },
        )
        return _parse_transaction(body)

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._base()}{path}",
                headers=self._headers(),
                json=payload,
            )
        return self._unwrap(response)

    async def _get(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self._base()}{path}", headers=self._headers())
        return self._unwrap(response)

    def _base(self) -> str:
        return str(self._settings.base_url).rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.secret()}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _unwrap(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as error:
            raise PaymentProviderRejectedError(
                f"Paystack returned a non-JSON response ({response.status_code})"
            ) from error
        if response.is_error or not body.get("status"):
            message = body.get("message") or f"status {response.status_code}"
            raise PaymentProviderRejectedError(f"Paystack rejected the request: {message}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise PaymentProviderRejectedError("Paystack returned no transaction data")
        return data


def _parse_transaction(data: dict[str, Any]) -> ProviderTransaction:
    reference = data.get("reference")
    if not isinstance(reference, str) or not reference:
        raise PaymentProviderRejectedError("Paystack returned no transaction reference")
    raw_status = str(data.get("status") or "").casefold()
    provider_reference = data.get("id")
    customer = data.get("customer")
    return ProviderTransaction(
        reference=reference,
        status=STATUS_BY_PROVIDER_VALUE.get(raw_status, PaymentTransactionStatus.FAILED),
        amount_minor=int(data.get("amount") or 0),
        currency=str(data.get("currency") or ""),
        provider_reference=str(provider_reference) if provider_reference else None,
        paid_at=_parse_timestamp(data.get("paid_at") or data.get("paidAt")),
        customer_email=(
            str(customer.get("email")) if isinstance(customer, dict) and customer.get("email")
            else None
        ),
        authorization=_parse_authorization(data.get("authorization")),
        gateway_message=_optional_str(data.get("gateway_response")),
    )


def _parse_authorization(value: Any) -> ProviderAuthorization | None:
    if not isinstance(value, dict):
        return None
    code = value.get("authorization_code")
    last_four = value.get("last4")
    if not isinstance(code, str) or not code:
        return None
    if not isinstance(last_four, str) or not last_four.isdigit() or len(last_four) != 4:
        return None
    channel = str(value.get("channel") or "").casefold()
    method_type = (
        PaymentMethodType.DIRECT_DEBIT
        if channel in {"bank", "bank_transfer", "direct_debit"}
        else PaymentMethodType.CARD
    )
    return ProviderAuthorization(
        authorization_code=code,
        method_type=method_type,
        last_four=last_four,
        card_brand=_optional_str(value.get("card_type")),
        bank_name=_optional_str(value.get("bank")),
        expiry_month=_optional_int(value.get("exp_month")),
        expiry_year=_optional_int(value.get("exp_year")),
        account_name=_optional_str(value.get("account_name")),
        reusable=bool(value.get("reusable")),
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
