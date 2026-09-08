"""The issuance sweep against real Postgres, inside a transaction it rolls back.

Everything here runs on a connection whose outer transaction is discarded, so
a test contract can never leak into the live schedule and bill a real school.
"""
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from nevo.billing.issuance import InvoiceIssuanceService
from nevo.core.config import get_settings
from nevo.db.models.account import School, User
from nevo.db.models.billing import Contract, Invoice
from nevo.db.session import create_engine
from nevo.domain.accounts.vocabulary import AuthMethod, UserRole, UserStatus
from nevo.domain.billing.vocabulary import (
    ContractStatus,
    PaymentSource,
    PricingCurrency,
    PricingPlan,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
    ),
]

TODAY = date(2026, 9, 8)


async def seeded(session, *, plan: PricingPlan, students: int, rate=None):  # type: ignore[no-untyped-def]
    token = uuid.uuid4().hex[:12]
    school = School(
        name="Issuance Test School",
        school_code=f"iss-{token}",
        school_url_slug=f"iss-{token}",
        pricing_plan=plan,
        per_student_rate=rate,
    )
    session.add(school)
    await session.flush()
    for _ in range(students):
        session.add(
            User(
                school_id=school.id,
                role=UserRole.STUDENT,
                auth_method=AuthMethod.PIN,
                status=UserStatus.ACTIVE,
            )
        )
    tier_id = await session.scalar(select(Contract.tier_id).limit(1))
    if tier_id is None:
        from nevo.db.models.billing import BillingSubscriptionTier

        tier_id = await session.scalar(select(BillingSubscriptionTier.tier_id).limit(1))
    session.add(
        Contract(
            school_id=school.id,
            tier_id=tier_id,
            status=ContractStatus.ACTIVE,
            is_founding_partner=False,
            payment_source=PaymentSource.DIRECT,
            start_date=TODAY - timedelta(days=1),
            end_date=TODAY + timedelta(days=364),
            current_year_index=1,
        )
    )
    await session.flush()
    return school


async def run_in_rollback(plan: PricingPlan, students: int, rate=None):  # type: ignore[no-untyped-def]
    engine = create_engine(get_settings().database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        sessions = async_sessionmaker(bind=connection, expire_on_commit=False)
        async with sessions() as setup:
            school = await seeded(setup, plan=plan, students=students, rate=rate)
            await setup.flush()

        service = InvoiceIssuanceService(sessions)
        first = await service.issue_due_invoices(today=TODAY)
        second = await service.issue_due_invoices(today=TODAY)

        async with sessions() as reader:
            invoices = list(
                await reader.scalars(
                    select(Invoice)
                    .where(Invoice.school_id == school.id)
                    .order_by(Invoice.invoice_number)
                )
            )
        return first, second, invoices
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


async def test_annual_school_is_billed_in_naira_per_student() -> None:
    _, second, invoices = await run_in_rollback(PricingPlan.ANNUAL, students=4)

    assert len(invoices) == 1
    invoice = invoices[0]
    assert invoice.currency is PricingCurrency.NGN
    assert invoice.student_count == 4
    assert invoice.per_student_rate == Decimal("150000.00")
    assert invoice.total_before_vat == Decimal("600000.00")
    assert invoice.vat_amount == Decimal("45000.00")
    assert invoice.amount == Decimal("645000.00")
    assert invoice.period_label == "Year 1"
    # Re-running the sweep must not bill the same school twice.
    assert second.issued == 0


async def test_per_term_school_gets_one_invoice_per_started_term() -> None:
    _, _, invoices = await run_in_rollback(PricingPlan.PER_TERM, students=4)

    # Only the first term has started as of TODAY.
    assert [invoice.period_label for invoice in invoices] == ["Year 1 Term 1"]
    assert invoices[0].per_student_rate == Decimal("55000.00")
    assert invoices[0].amount == Decimal("236500.00")


async def test_a_negotiated_rate_is_what_the_school_is_billed() -> None:
    _, _, invoices = await run_in_rollback(
        PricingPlan.ANNUAL, students=10, rate=Decimal("90000.00")
    )

    assert invoices[0].per_student_rate == Decimal("90000.00")
    assert invoices[0].total_before_vat == Decimal("900000.00")
    assert invoices[0].amount == Decimal("967500.00")


async def test_the_contract_year_advances_once_the_year_is_fully_invoiced() -> None:
    """Nothing moved this index before, so billing stopped after year one."""
    engine = create_engine(get_settings().database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        sessions = async_sessionmaker(bind=connection, expire_on_commit=False)
        async with sessions() as setup:
            school = await seeded(setup, plan=PricingPlan.ANNUAL, students=2)
            await setup.flush()

        service = InvoiceIssuanceService(sessions)
        await service.issue_due_invoices(today=TODAY)

        async with sessions() as reader:
            year_one = await reader.scalar(
                select(Contract.current_year_index).where(Contract.school_id == school.id)
            )

        # A year later the sweep runs again: the index moves and year two bills.
        await service.issue_due_invoices(today=TODAY + timedelta(days=366))

        async with sessions() as reader:
            year_two = await reader.scalar(
                select(Contract.current_year_index).where(Contract.school_id == school.id)
            )
            numbers = sorted(
                await reader.scalars(
                    select(Invoice.invoice_number).where(Invoice.school_id == school.id)
                )
            )

        assert year_one == 1
        assert year_two == 2
        assert [number.split("-")[-1] for number in numbers] == ["Y1", "Y2"]
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()
