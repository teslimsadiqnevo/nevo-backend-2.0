from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol
from uuid import UUID

from nevo.billing.entities import (
    BillingContactRecord,
    BillingContactUpdate,
    BillingLedgerQuote,
    InvoiceRecord,
    PaymentMethodRecord,
    PaymentMethodUpdate,
    SubscriptionRecord,
    UpcomingCharge,
)
from nevo.billing.errors import BillingPaymentMethodError
from nevo.domain.billing.vocabulary import (
    InvoiceStatus,
    PaymentMethodType,
    PricingCurrency,
    SubscriptionTier,
)

VAT_RATE = Decimal("7.50")
VOLATILITY_BUFFER_PERCENT = Decimal("5.00")
FOUNDING_PARTNER_RATES_USD = {
    SubscriptionTier.BOUTIQUE: Decimal("25000.00"),
    SubscriptionTier.MID_MARKET: Decimal("50000.00"),
    SubscriptionTier.PREMIUM: Decimal("80000.00"),
    SubscriptionTier.ENTERPRISE: Decimal("140000.00"),
}
COMMERCIAL_RATES_USD = {
    SubscriptionTier.BOUTIQUE: Decimal("40000.00"),
    SubscriptionTier.MID_MARKET: Decimal("80000.00"),
    SubscriptionTier.PREMIUM: Decimal("125000.00"),
    SubscriptionTier.ENTERPRISE: Decimal("220000.00"),
}
STEP_UP_DISCOUNTS = {
    1: Decimal("37.50"),
    2: Decimal("37.50"),
    3: Decimal("37.50"),
    4: Decimal("20.00"),
    5: Decimal("10.00"),
    6: Decimal("0.00"),
}


class BillingRepository(Protocol):
    async def subscription(self, school_id: UUID) -> SubscriptionRecord: ...

    async def invoices(
        self,
        *,
        school_id: UUID,
        date_from: date | None,
        date_to: date | None,
        status: InvoiceStatus | None,
    ) -> tuple[InvoiceRecord, ...]: ...

    async def upcoming(self, school_id: UUID) -> UpcomingCharge: ...

    async def update_payment_method(
        self,
        *,
        school_id: UUID,
        actor_user_id: UUID,
        update_data: PaymentMethodUpdate,
    ) -> PaymentMethodRecord: ...

    async def update_billing_contact(
        self,
        *,
        school_id: UUID,
        actor_user_id: UUID,
        update_data: BillingContactUpdate,
    ) -> BillingContactRecord: ...


class BillingService:
    def __init__(self, repository: BillingRepository) -> None:
        self._repository = repository

    async def subscription(self, school_id: UUID) -> SubscriptionRecord:
        return await self._repository.subscription(school_id)

    async def invoices(
        self,
        *,
        school_id: UUID,
        date_from: date | None,
        date_to: date | None,
        status: InvoiceStatus | None,
    ) -> tuple[InvoiceRecord, ...]:
        return await self._repository.invoices(
            school_id=school_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )

    async def upcoming(self, school_id: UUID) -> UpcomingCharge:
        return await self._repository.upcoming(school_id)

    async def update_payment_method(
        self,
        *,
        school_id: UUID,
        actor_user_id: UUID,
        update_data: PaymentMethodUpdate,
    ) -> PaymentMethodRecord:
        if update_data.method_type is PaymentMethodType.CARD:
            if update_data.expiry_month is None or update_data.expiry_year is None:
                raise BillingPaymentMethodError
        return await self._repository.update_payment_method(
            school_id=school_id,
            actor_user_id=actor_user_id,
            update_data=update_data,
        )

    async def update_billing_contact(
        self,
        *,
        school_id: UUID,
        actor_user_id: UUID,
        update_data: BillingContactUpdate,
    ) -> BillingContactRecord:
        return await self._repository.update_billing_contact(
            school_id=school_id,
            actor_user_id=actor_user_id,
            update_data=update_data,
        )


def quote_annual_invoice(
    *,
    tier: SubscriptionTier,
    is_founding_partner: bool,
    year_index: int,
    billed_currency: PricingCurrency,
    fx_rate: Decimal = Decimal("1.000000"),
    volatility_buffer_percent: Decimal = VOLATILITY_BUFFER_PERCENT,
) -> BillingLedgerQuote:
    if year_index < 1 or year_index > 6:
        raise ValueError("year_index must be between 1 and 6")
    if billed_currency is PricingCurrency.NGN and fx_rate <= 0:
        raise ValueError("fx_rate must be positive for NGN billing")
    amount_usd = _amount_for_contract_year(
        tier=tier,
        is_founding_partner=is_founding_partner,
        year_index=year_index,
    )
    commercial_amount = COMMERCIAL_RATES_USD[tier]
    discount = _discount_percent(
        amount_usd=amount_usd,
        commercial_amount=commercial_amount,
    )
    vat_amount = _money(amount_usd * VAT_RATE / Decimal("100"))
    total_usd = _money(amount_usd + vat_amount)
    applied_fx = _fx_rate_with_buffer(
        billed_currency=billed_currency,
        fx_rate=fx_rate,
        volatility_buffer_percent=volatility_buffer_percent,
    )
    return BillingLedgerQuote(
        tier=tier,
        amount_usd=commercial_amount,
        applied_discount_percent=discount,
        net_amount_usd=amount_usd,
        vat_amount_usd=vat_amount,
        total_with_vat_usd=total_usd,
        billed_currency=billed_currency,
        fx_rate_applied=applied_fx,
        total_billed_local=_money(total_usd * applied_fx),
    )


def _amount_for_contract_year(
    *,
    tier: SubscriptionTier,
    is_founding_partner: bool,
    year_index: int,
) -> Decimal:
    if is_founding_partner and year_index <= 3:
        return FOUNDING_PARTNER_RATES_USD[tier]
    commercial = COMMERCIAL_RATES_USD[tier]
    discount = STEP_UP_DISCOUNTS.get(year_index, Decimal("0.00"))
    return _money(commercial * (Decimal("100") - discount) / Decimal("100"))


def _discount_percent(
    *,
    amount_usd: Decimal,
    commercial_amount: Decimal,
) -> Decimal:
    discount = (Decimal("1") - (amount_usd / commercial_amount)) * Decimal("100")
    return discount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fx_rate_with_buffer(
    *,
    billed_currency: PricingCurrency,
    fx_rate: Decimal,
    volatility_buffer_percent: Decimal,
) -> Decimal:
    if billed_currency is PricingCurrency.USD:
        return Decimal("1.000000")
    return (fx_rate * (Decimal("1") + volatility_buffer_percent / Decimal("100"))).quantize(
        Decimal("0.000001"),
        rounding=ROUND_HALF_UP,
    )


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
