import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.billing.service import quote_per_student
from nevo.db.models.account import School, User
from nevo.db.models.billing import BillingContact, BillingEmailDelivery, Contract, Invoice
from nevo.db.models.consent import ParentLink
from nevo.domain.accounts.vocabulary import NotificationType, UserRole, UserStatus
from nevo.domain.billing.vocabulary import (
    ContractStatus,
    InvoiceStatus,
    PricingCurrency,
    PricingPlan,
    RateType,
)
from nevo.notifications.dispatch import notify_each

logger = logging.getLogger(__name__)

PAYMENT_TERM_DAYS = 30
DAYS_PER_CONTRACT_YEAR = 365
MAX_CONTRACT_YEARS = 6
"""The contracts table constrains current_year_index to 1..6."""

TERMS_PER_YEAR = 3
"""Nigerian schools run three terms, so a per-term contract bills three times."""

TERM_DATES_KEY = "term_start_dates"
"""Where a school's own term start dates live in ``academic_config``."""


@dataclass(frozen=True, slots=True)
class BillingPeriod:
    """One thing to invoice for: a contract year, or a term within one."""

    number: str
    label: str
    starts_on: date


@dataclass(frozen=True, slots=True)
class IssuanceResult:
    considered: int
    issued: int

    def summary(self) -> str:
        return f"issued {self.issued} invoices from {self.considered} active contracts"


class InvoiceIssuanceService:
    """Raises each school's invoices as their billing periods come due.

    Prices per student off the school's own rate and live head count, in
    naira. An invoice is issued at most once per period: the deterministic
    invoice number doubles as the idempotency key, so re-running the sweep
    cannot bill a school twice.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        billed_currency: PricingCurrency = PricingCurrency.NGN,
    ) -> None:
        self._sessions = sessions
        self._billed_currency = billed_currency

    async def issue_due_invoices(self, *, today: date | None = None) -> IssuanceResult:
        issue_date = today or datetime.now(UTC).date()
        issued = 0
        async with self._sessions.begin() as session:
            rows = (
                await session.execute(
                    select(Contract, School)
                    .join(School, School.id == Contract.school_id)
                    .where(Contract.status == ContractStatus.ACTIVE)
                )
            ).all()

            for contract, school in rows:
                student_count, activation_ids = await self._billable_students(session, school.id)
                term_starts = self._configured_terms(school)
                # Catch up year by year: a sweep that has not run in a while
                # still bills every period it missed, in order.
                for _ in range(MAX_CONTRACT_YEARS):
                    outstanding = 0
                    for period in self.periods_for(
                        plan=school.pricing_plan,
                        school_code=school.school_code,
                        contract_start=contract.start_date,
                        year_index=contract.current_year_index,
                        term_start_dates=term_starts,
                    ):
                        already_issued = await session.scalar(
                            select(Invoice.id).where(Invoice.invoice_number == period.number)
                        )
                        if already_issued is not None:
                            continue
                        if period.starts_on > issue_date:
                            outstanding += 1
                            continue
                        quote = quote_per_student(
                            plan=school.pricing_plan,
                            student_count=student_count,
                            rate_type=(
                                RateType.FOUNDING_PARTNER
                                if contract.is_founding_partner or school.is_founding_partner
                                else RateType.STANDARD
                            ),
                            per_student_rate=school.per_student_rate,
                            rate_locked_until=school.price_lock_expiry,
                            currency=self._billed_currency,
                        )
                        invoice = Invoice(
                            invoice_number=period.number,
                            school_id=school.id,
                            issued_at=issue_date,
                            amount=quote.total_with_vat,
                            currency=quote.currency,
                            student_count=quote.student_count,
                            activation_student_ids=activation_ids,
                            per_student_rate=quote.per_student_rate,
                            total_before_vat=quote.total_before_vat,
                            vat_amount=quote.vat_amount,
                            vat_rate=quote.vat_rate,
                            period_label=period.label,
                            status=InvoiceStatus.PENDING,
                            due_at=issue_date + timedelta(days=PAYMENT_TERM_DAYS),
                            pdf_url=(f"/api/billing/invoices/{school.id}/{period.number}.pdf"),
                        )
                        session.add(invoice)
                        await session.flush()
                        await queue_billing_emails(session, invoice=invoice, kind="issued")
                        # An invoice nobody is told about is an invoice nobody
                        # pays. invoice_issued had a category and a preference
                        # switch and was never once raised.
                        await _notify_billing_contacts(
                            session,
                            school=school,
                            number=period.number,
                            label=period.label,
                            amount=quote.total_with_vat,
                            currency=quote.currency,
                            due_on=issue_date + timedelta(days=PAYMENT_TERM_DAYS),
                        )
                        issued += 1
                    if outstanding or not self._advance_contract_year(contract, issue_date):
                        break
        return IssuanceResult(considered=len(rows), issued=issued)

    @classmethod
    def _advance_contract_year(cls, contract: Contract, issue_date: date) -> bool:
        """Move to the next contract year once this one is fully invoiced.

        Nothing moved this index before, so a contract stopped being billed
        after its first year. Returns whether it moved.
        """
        next_index = contract.current_year_index + 1
        if next_index > MAX_CONTRACT_YEARS:
            return False
        next_start = cls._period_start(contract.start_date, next_index)
        if next_start > issue_date or next_start > contract.end_date:
            return False
        contract.current_year_index = next_index
        return True

    @staticmethod
    async def _billable_students(session: AsyncSession, school_id):  # type: ignore[no-untyped-def]
        """The children a school pays for this period, and which to activate.

        The roster, whether or not consent has come back: the school is the
        only party who can chase a parent, and a lower bill for an
        outstanding consent would be a reason not to.

        SCRUM-309 is the one exception. A child with no parent address has
        nothing to send, so no consent request exists and no removal
        countdown has started - they would sit on the roster being billed
        with nothing counting down, which is the indefinite billing that
        countdown exists to prevent, arriving by another door. They enter
        the count on the day an address is added and the request goes out.
        That is not the school being let off; it is a child nobody can act
        on yet, and the screen listing them stays so somebody adds it.
        """

        rows = (
            await session.execute(
                select(User.id, User.status).where(
                    User.school_id == school_id,
                    User.role == UserRole.STUDENT,
                    User.status.in_([UserStatus.ACTIVE, UserStatus.INVITED]),
                    select(ParentLink.id)
                    .where(
                        ParentLink.student_id == User.id,
                        ParentLink.parent_contact != "",
                    )
                    .exists(),
                )
            )
        ).all()
        return len(rows), [str(user_id) for user_id, state in rows if state == UserStatus.INVITED]

    @classmethod
    def periods_for(
        cls,
        *,
        plan: PricingPlan,
        school_code: str,
        contract_start: date,
        year_index: int,
        term_start_dates: tuple[date, ...] = (),
    ) -> tuple[BillingPeriod, ...]:
        """The periods of one contract year that this school pays for."""
        year_start = cls._period_start(contract_start, year_index)
        if plan is PricingPlan.ANNUAL:
            return (
                BillingPeriod(
                    number=cls._invoice_number(school_code, year_index),
                    label=f"Year {year_index}",
                    starts_on=year_start,
                ),
            )
        starts = cls._term_starts(year_start, term_start_dates)
        return tuple(
            BillingPeriod(
                number=cls._invoice_number(school_code, year_index, term=term_index),
                label=f"Year {year_index} Term {term_index}",
                starts_on=starts[term_index - 1],
            )
            for term_index in range(1, TERMS_PER_YEAR + 1)
        )

    @classmethod
    def _term_starts(
        cls,
        year_start: date,
        term_start_dates: tuple[date, ...],
    ) -> tuple[date, ...]:
        """Prefer the school's own term dates; divide the year if it has none.

        A school that has not configured its calendar still has to be billed,
        and an evenly divided year is at least predictable. The fallback is
        logged so it is visible rather than silently assumed.
        """
        if len(term_start_dates) == TERMS_PER_YEAR:
            return term_start_dates
        if term_start_dates:
            logger.warning(
                "School term dates ignored: expected %s, got %s",
                TERMS_PER_YEAR,
                len(term_start_dates),
            )
        span = DAYS_PER_CONTRACT_YEAR // TERMS_PER_YEAR
        return tuple(year_start + timedelta(days=span * index) for index in range(TERMS_PER_YEAR))

    @staticmethod
    def _configured_terms(school: School) -> tuple[date, ...]:
        raw = school.academic_config.get(TERM_DATES_KEY)
        if not isinstance(raw, list):
            return ()
        parsed: list[date] = []
        for item in raw:
            try:
                parsed.append(date.fromisoformat(str(item)))
            except ValueError:
                logger.warning(
                    "School %s has an unreadable term start date: %r",
                    school.id,
                    item,
                )
                return ()
        return tuple(sorted(parsed))

    @staticmethod
    def _period_start(start_date: date, year_index: int) -> date:
        """The date the given contract year begins."""
        return start_date + timedelta(days=DAYS_PER_CONTRACT_YEAR * (year_index - 1))

    @staticmethod
    def _invoice_number(school_code: str, year_index: int, *, term: int | None = None) -> str:
        slug = "".join(char for char in school_code.upper() if char.isalnum())[:20]
        if term is None:
            return f"NEVO-{slug}-Y{year_index}"
        return f"NEVO-{slug}-Y{year_index}T{term}"


async def _notify_billing_contacts(
    session: AsyncSession,
    *,
    school: School,
    number: str,
    label: str,
    amount: Decimal,
    currency: PricingCurrency,
    due_on: date,
) -> None:
    """Tell whoever handles this school's money that a bill exists."""

    admins = (
        await session.scalars(
            select(User).where(
                User.school_id == school.id,
                User.role.in_({UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}),
                User.status == UserStatus.ACTIVE,
            )
        )
    ).all()
    if not admins:
        logger.warning("Invoice %s raised for %s with no active admin to tell", number, school.id)
        return
    await notify_each(
        session,
        recipients=[(admin.id, admin.role) for admin in admins],
        notification_type=NotificationType.INVOICE_ISSUED,
        title=f"Invoice {number} is ready",
        description=(f"{label}: {currency.value} {amount:,.2f}, due {due_on.isoformat()}."),
        navigates_to="/admin/billing",
    )


async def queue_billing_emails(session: AsyncSession, *, invoice: Invoice, kind: str) -> int:
    """Queue each invoice message once per listed address and milestone.

    Every contact the school has listed, not only the primary one. The
    primary is who checkout is attributed to; being able to read the bill is
    a different question, and naming several people is the point of the
    screen.
    """

    emails = set(
        await session.scalars(
            select(BillingContact.email).where(BillingContact.school_id == invoice.school_id)
        )
    )
    if not emails:
        # A school that has never filled the contacts screen in. Nothing is
        # queued, so the invoice reaches nobody by email - the in-app notice
        # is all there is, and it goes to admins who may be exactly the
        # people who cannot act on it. Said out loud because the alternative
        # is an unpaid invoice nobody was ever sent.
        logger.warning(
            "Invoice %s for school %s has no billing contact to email",
            invoice.invoice_number,
            invoice.school_id,
        )
        return 0
    existing = set(
        await session.scalars(
            select(BillingEmailDelivery.email).where(
                BillingEmailDelivery.invoice_id == invoice.id,
                BillingEmailDelivery.kind == kind,
            )
        )
    )
    for email in emails - existing:
        session.add(
            BillingEmailDelivery(
                invoice_id=invoice.id,
                email=email,
                kind=kind,
            )
        )
    return len(emails - existing)
