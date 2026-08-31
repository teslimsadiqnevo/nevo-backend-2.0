import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.billing.service import quote_annual_invoice
from nevo.db.models.account import School
from nevo.db.models.billing import BillingSubscriptionTier, Contract, Invoice
from nevo.domain.billing.vocabulary import (
    ContractStatus,
    InvoiceStatus,
    PricingCurrency,
)

logger = logging.getLogger(__name__)

PAYMENT_TERM_DAYS = 30
DAYS_PER_CONTRACT_YEAR = 365


@dataclass(frozen=True, slots=True)
class IssuanceResult:
    considered: int
    issued: int

    def summary(self) -> str:
        return f"issued {self.issued} invoices from {self.considered} active contracts"


class InvoiceIssuanceService:
    """Raises the invoice for each contract year as it comes due.

    An invoice is only issued once per contract year: the deterministic
    invoice number doubles as the idempotency key, so re-running the sweep
    cannot bill a school twice.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        billed_currency: PricingCurrency = PricingCurrency.USD,
    ) -> None:
        self._sessions = sessions
        self._billed_currency = billed_currency

    async def issue_due_invoices(self, *, today: date | None = None) -> IssuanceResult:
        issue_date = today or datetime.now(UTC).date()
        issued = 0
        async with self._sessions.begin() as session:
            rows = (
                await session.execute(
                    select(Contract, BillingSubscriptionTier.tier_name, School.school_code)
                    .join(
                        BillingSubscriptionTier,
                        BillingSubscriptionTier.tier_id == Contract.tier_id,
                    )
                    .join(School, School.id == Contract.school_id)
                    .where(Contract.status == ContractStatus.ACTIVE)
                )
            ).all()

            for contract, tier_name, school_code in rows:
                period_start = self._period_start(contract.start_date, contract.current_year_index)
                if period_start > issue_date:
                    continue
                number = self._invoice_number(school_code, contract.current_year_index)
                already_issued = await session.scalar(
                    select(Invoice.id).where(Invoice.invoice_number == number)
                )
                if already_issued is not None:
                    continue
                quote = quote_annual_invoice(
                    tier=tier_name,
                    is_founding_partner=contract.is_founding_partner,
                    year_index=contract.current_year_index,
                    billed_currency=self._billed_currency,
                )
                session.add(
                    Invoice(
                        invoice_number=number,
                        school_id=contract.school_id,
                        issued_at=issue_date,
                        amount=quote.total_with_vat_usd,
                        status=InvoiceStatus.PENDING,
                        due_at=issue_date + timedelta(days=PAYMENT_TERM_DAYS),
                        pdf_url=(
                            f"/api/billing/invoices/{contract.school_id}/{number}.pdf"
                        ),
                    )
                )
                issued += 1
        return IssuanceResult(considered=len(rows), issued=issued)

    @staticmethod
    def _period_start(start_date: date, year_index: int) -> date:
        """The date the given contract year begins."""
        return start_date + timedelta(days=DAYS_PER_CONTRACT_YEAR * (year_index - 1))

    @staticmethod
    def _invoice_number(school_code: str, year_index: int) -> str:
        slug = "".join(char for char in school_code.upper() if char.isalnum())[:20]
        return f"NEVO-{slug}-Y{year_index}"
