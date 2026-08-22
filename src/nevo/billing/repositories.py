from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.billing.entities import (
    BillingContactRecord,
    BillingContactUpdate,
    InvoiceRecord,
    PaymentMethodRecord,
    PaymentMethodUpdate,
    SubscriptionRecord,
    UpcomingCharge,
)
from nevo.billing.errors import BillingNotFoundError
from nevo.db.models.account import School
from nevo.db.models.billing import BillingContact, BillingPaymentMethod, Invoice
from nevo.domain.billing.vocabulary import InvoiceStatus

RENEWAL_NOTICE_DAYS = 60


class SqlAlchemyBillingRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._sessions = sessions
        self._today = today or (lambda: datetime.now(UTC).date())

    async def subscription(self, school_id: UUID) -> SubscriptionRecord:
        async with self._sessions() as session:
            school = await session.get(School, school_id)
            if school is None:
                raise BillingNotFoundError
            contact = await _billing_contact(session, school.billing_contact_id)
            payment_method = await session.scalar(
                select(BillingPaymentMethod).where(
                    BillingPaymentMethod.school_id == school_id
                )
            )
        visible, message = _renewal_notice(school.contract_end, self._today())
        return SubscriptionRecord(
            school_id=school.id,
            school_name=school.name,
            subscription_tier=school.subscription_tier,
            student_count_band=school.enrollment_band,
            contract_value=school.contract_value,
            contract_start=school.contract_start,
            contract_end=school.contract_end,
            renewal_banner_visible=visible,
            renewal_message=message,
            billing_contact=_contact_record(contact) if contact else None,
            payment_method=(
                _payment_method_record(payment_method) if payment_method else None
            ),
        )

    async def invoices(
        self,
        *,
        school_id: UUID,
        date_from: date | None,
        date_to: date | None,
        status: InvoiceStatus | None,
    ) -> tuple[InvoiceRecord, ...]:
        query: Select[tuple[Invoice]] = select(Invoice).where(
            Invoice.school_id == school_id
        )
        if date_from is not None:
            query = query.where(Invoice.issued_at >= date_from)
        if date_to is not None:
            query = query.where(Invoice.issued_at <= date_to)
        if status is not None:
            query = query.where(Invoice.status == status)
        query = query.order_by(Invoice.issued_at.desc(), Invoice.invoice_number.desc())
        async with self._sessions() as session:
            rows = (await session.scalars(query)).all()
        return tuple(_invoice_record(row) for row in rows)

    async def upcoming(self, school_id: UUID) -> UpcomingCharge:
        today = self._today()
        async with self._sessions() as session:
            school = await session.get(School, school_id)
            if school is None:
                raise BillingNotFoundError
            invoice = await session.scalar(
                select(Invoice)
                .where(
                    Invoice.school_id == school_id,
                    Invoice.status.in_(
                        [InvoiceStatus.PENDING, InvoiceStatus.OVERDUE]
                    ),
                    Invoice.due_at >= today,
                )
                .order_by(Invoice.due_at)
                .limit(1)
            )
        visible, message = _renewal_notice(school.contract_end, today)
        if invoice is None:
            return UpcomingCharge(
                invoice_id=None,
                invoice_number=None,
                due_at=None,
                amount=None,
                status=None,
                renewal_banner_visible=visible,
                renewal_message=message,
            )
        return UpcomingCharge(
            invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            due_at=invoice.due_at,
            amount=invoice.amount,
            status=invoice.status,
            renewal_banner_visible=visible,
            renewal_message=message,
        )

    async def update_payment_method(
        self,
        *,
        school_id: UUID,
        actor_user_id: UUID,
        update_data: PaymentMethodUpdate,
    ) -> PaymentMethodRecord:
        async with self._sessions.begin() as session:
            record = await session.scalar(
                select(BillingPaymentMethod).where(
                    BillingPaymentMethod.school_id == school_id
                )
            )
            values = {
                "method_type": update_data.method_type,
                "processor_name": update_data.processor_name,
                "processor_payment_method_ref": (
                    update_data.processor_payment_method_ref
                ),
                "display_name": update_data.display_name,
                "last_four": update_data.last_four,
                "card_brand": update_data.card_brand,
                "expiry_month": update_data.expiry_month,
                "expiry_year": update_data.expiry_year,
                "bank_name": update_data.bank_name,
                "account_holder_name": update_data.account_holder_name,
                "updated_by_user_id": actor_user_id,
                "updated_at": datetime.now(UTC),
            }
            if record is None:
                record = BillingPaymentMethod(
                    id=uuid4(),
                    school_id=school_id,
                    **values,
                )
                session.add(record)
                await session.flush()
            else:
                await session.execute(
                    update(BillingPaymentMethod)
                    .where(BillingPaymentMethod.id == record.id)
                    .values(**values)
                )
                await session.refresh(record)
        return _payment_method_record(record)

    async def update_billing_contact(
        self,
        *,
        school_id: UUID,
        actor_user_id: UUID,
        update_data: BillingContactUpdate,
    ) -> BillingContactRecord:
        async with self._sessions.begin() as session:
            record = await session.scalar(
                select(BillingContact).where(BillingContact.school_id == school_id)
            )
            values = {
                "email": update_data.email,
                "phone": update_data.phone,
                "address_line1": update_data.address_line1,
                "address_line2": update_data.address_line2,
                "city": update_data.city,
                "region": update_data.region,
                "postal_code": update_data.postal_code,
                "country": update_data.country,
                "updated_by_user_id": actor_user_id,
                "updated_at": datetime.now(UTC),
            }
            if record is None:
                record = BillingContact(
                    id=uuid4(),
                    school_id=school_id,
                    **values,
                )
                session.add(record)
                await session.flush()
                await session.execute(
                    update(School)
                    .where(School.id == school_id)
                    .values(billing_contact_id=record.id)
                )
            else:
                await session.execute(
                    update(BillingContact)
                    .where(BillingContact.id == record.id)
                    .values(**values)
                )
                await session.refresh(record)
        return _contact_record(record)


async def _billing_contact(
    session: AsyncSession,
    billing_contact_id: UUID | None,
) -> BillingContact | None:
    if billing_contact_id is None:
        return None
    return await session.get(BillingContact, billing_contact_id)


def _renewal_notice(
    contract_end: datetime | None,
    today: date,
) -> tuple[bool, str | None]:
    if contract_end is None:
        return False, None
    renewal_date = contract_end.date()
    if today <= renewal_date <= today + timedelta(days=RENEWAL_NOTICE_DAYS):
        return (
            True,
            f"Your current contract renews on {renewal_date.isoformat()}.",
        )
    return False, None


def _contact_record(record: BillingContact) -> BillingContactRecord:
    return BillingContactRecord(
        id=record.id,
        email=record.email,
        phone=record.phone,
        address_line1=record.address_line1,
        address_line2=record.address_line2,
        city=record.city,
        region=record.region,
        postal_code=record.postal_code,
        country=record.country,
    )


def _payment_method_record(record: BillingPaymentMethod) -> PaymentMethodRecord:
    return PaymentMethodRecord(
        id=record.id,
        method_type=record.method_type,
        display_name=record.display_name,
        last_four=record.last_four,
        card_brand=record.card_brand,
        expiry_month=record.expiry_month,
        expiry_year=record.expiry_year,
        bank_name=record.bank_name,
        account_holder_name=record.account_holder_name,
        updated_at=record.updated_at,
    )


def _invoice_record(record: Invoice) -> InvoiceRecord:
    return InvoiceRecord(
        id=record.id,
        invoice_number=record.invoice_number,
        issued_at=record.issued_at,
        amount=record.amount,
        status=record.status,
        due_at=record.due_at,
        paid_at=record.paid_at,
        pdf_url=record.pdf_url,
    )


def invoice_pdf_url(
    *,
    school_id: UUID,
    invoice_number: str,
) -> str:
    """Stable storage path used when invoice issue jobs create PDFs."""

    return f"/api/billing/invoices/{school_id}/{invoice_number}.pdf"
