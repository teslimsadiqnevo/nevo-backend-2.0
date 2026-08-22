from datetime import date
from typing import Protocol
from uuid import UUID

from nevo.billing.entities import (
    BillingContactRecord,
    BillingContactUpdate,
    InvoiceRecord,
    PaymentMethodRecord,
    PaymentMethodUpdate,
    SubscriptionRecord,
    UpcomingCharge,
)
from nevo.billing.errors import BillingPaymentMethodError
from nevo.domain.billing.vocabulary import InvoiceStatus, PaymentMethodType


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
