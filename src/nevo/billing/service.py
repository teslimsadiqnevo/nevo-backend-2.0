from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol
from uuid import UUID

from nevo.billing.entities import (
    BillingContactRecord,
    BillingContactUpdate,
    InvoiceRecord,
    PaymentMethodRecord,
    PaymentMethodUpdate,
    PerStudentQuote,
    SubscriptionRecord,
    UpcomingCharge,
)
from nevo.billing.errors import BillingPaymentMethodError
from nevo.domain.billing.vocabulary import (
    AccessWindow,
    InvoiceStatus,
    PaymentMethodType,
    PricingCurrency,
    PricingPlan,
    RateType,
)

VAT_RATE = Decimal("7.50")
PUBLISHED_RATES_NGN: dict[PricingPlan, Decimal] = {
    PricingPlan.ANNUAL: Decimal("150000.00"),
    PricingPlan.PER_TERM: Decimal("55000.00"),
}
"""The rate card, per student, in naira.

Annual buys 365 days including breaks; per-term buys the school's session
only. A school with a negotiated rate carries its own on the school row and
this is the fallback, so the published price is stated once.
"""

ACCESS_WINDOWS: dict[PricingPlan, AccessWindow] = {
    PricingPlan.ANNUAL: AccessWindow.YEAR_ROUND,
    PricingPlan.PER_TERM: AccessWindow.SCHOOL_SESSION,
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


def published_rate(plan: PricingPlan) -> Decimal:
    return PUBLISHED_RATES_NGN[plan]


def quote_per_student(
    *,
    plan: PricingPlan,
    student_count: int,
    rate_type: RateType,
    per_student_rate: Decimal | None = None,
    rate_locked_until: datetime | None = None,
    currency: PricingCurrency = PricingCurrency.NGN,
) -> PerStudentQuote:
    """Price a school off its head count.

    The rate is the input and the total is derived, which is the way round
    per-student pricing works. It used to be inferred the other way - a
    contract value divided by however many learners happened to be active -
    so the rate moved every time somebody was enrolled.
    """
    if student_count < 0:
        raise ValueError("student_count cannot be negative")
    rate = per_student_rate if per_student_rate is not None else published_rate(plan)
    if rate < 0:
        raise ValueError("per_student_rate cannot be negative")
    total_before_vat = _money(rate * student_count)
    vat_amount = _money(total_before_vat * VAT_RATE / Decimal("100"))
    return PerStudentQuote(
        pricing_plan=plan,
        student_count=student_count,
        per_student_rate=_money(rate),
        rate_type=rate_type,
        rate_locked_until=rate_locked_until,
        access_window=ACCESS_WINDOWS[plan],
        total_before_vat=total_before_vat,
        vat_rate=VAT_RATE,
        vat_amount=vat_amount,
        total_with_vat=_money(total_before_vat + vat_amount),
        currency=currency,
    )


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
