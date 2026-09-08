"""Per-student pricing: the rate is the input, the total is derived."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nevo.billing.config import BankTransferSettings
from nevo.billing.service import PUBLISHED_RATES_NGN, quote_per_student
from nevo.domain.billing.vocabulary import (
    AccessWindow,
    PricingCurrency,
    PricingPlan,
    RateType,
)


def test_annual_plan_prices_at_the_published_naira_rate() -> None:
    quote = quote_per_student(
        plan=PricingPlan.ANNUAL,
        student_count=200,
        rate_type=RateType.STANDARD,
    )

    assert quote.per_student_rate == Decimal("150000.00")
    assert quote.total_before_vat == Decimal("30000000.00")
    assert quote.vat_rate == Decimal("7.50")
    assert quote.vat_amount == Decimal("2250000.00")
    assert quote.total_with_vat == Decimal("32250000.00")
    assert quote.currency is PricingCurrency.NGN
    assert quote.access_window is AccessWindow.YEAR_ROUND


def test_per_term_plan_prices_per_term_and_covers_only_the_session() -> None:
    quote = quote_per_student(
        plan=PricingPlan.PER_TERM,
        student_count=200,
        rate_type=RateType.STANDARD,
    )

    assert quote.per_student_rate == Decimal("55000.00")
    assert quote.total_before_vat == Decimal("11000000.00")
    assert quote.total_with_vat == Decimal("11825000.00")
    # Per-term buys the school's session, not the calendar year.
    assert quote.access_window is AccessWindow.SCHOOL_SESSION


def test_three_terms_cost_more_than_a_year_at_the_published_rates() -> None:
    """Worth stating: per-term is not a discount, it is a cashflow option."""
    annual = quote_per_student(
        plan=PricingPlan.ANNUAL, student_count=1, rate_type=RateType.STANDARD
    )
    per_term = quote_per_student(
        plan=PricingPlan.PER_TERM, student_count=1, rate_type=RateType.STANDARD
    )

    assert per_term.per_student_rate * 3 == Decimal("165000.00")
    assert per_term.per_student_rate * 3 > annual.per_student_rate


def test_a_negotiated_rate_overrides_the_rate_card() -> None:
    quote = quote_per_student(
        plan=PricingPlan.ANNUAL,
        student_count=10,
        rate_type=RateType.FOUNDING_PARTNER,
        per_student_rate=Decimal("100000.00"),
        rate_locked_until=datetime(2029, 9, 1, tzinfo=UTC),
    )

    assert quote.per_student_rate == Decimal("100000.00")
    assert quote.total_before_vat == Decimal("1000000.00")
    assert quote.rate_type is RateType.FOUNDING_PARTNER
    assert quote.rate_locked_until == datetime(2029, 9, 1, tzinfo=UTC)


def test_a_school_with_no_learners_owes_nothing() -> None:
    quote = quote_per_student(
        plan=PricingPlan.ANNUAL, student_count=0, rate_type=RateType.STANDARD
    )

    assert quote.total_before_vat == Decimal("0.00")
    assert quote.vat_amount == Decimal("0.00")
    assert quote.total_with_vat == Decimal("0.00")


def test_negative_inputs_are_refused() -> None:
    with pytest.raises(ValueError):
        quote_per_student(
            plan=PricingPlan.ANNUAL, student_count=-1, rate_type=RateType.STANDARD
        )
    with pytest.raises(ValueError):
        quote_per_student(
            plan=PricingPlan.ANNUAL,
            student_count=1,
            rate_type=RateType.STANDARD,
            per_student_rate=Decimal("-1.00"),
        )


def test_the_rate_card_is_the_one_the_ceo_confirmed() -> None:
    assert PUBLISHED_RATES_NGN == {
        PricingPlan.ANNUAL: Decimal("150000.00"),
        PricingPlan.PER_TERM: Decimal("55000.00"),
    }


def test_bank_transfer_details_default_to_the_receiving_account() -> None:
    details = BankTransferSettings().details()

    assert details.bank_name == "Kuda Bank"
    assert details.account_number == "3004167012"
    assert details.account_name == "Nevo Learning Limited"
    assert details.currency is PricingCurrency.NGN


def test_the_invoice_pdf_shows_the_working_not_just_the_total() -> None:
    """A bursar has to be able to check a per-student bill, not trust it."""
    from decimal import Decimal as D

    from nevo.api.billing import _invoice_working
    from nevo.db.models.billing import Invoice

    lines = _invoice_working(
        Invoice(
            currency=PricingCurrency.NGN,
            period_label="Year 1 Term 2",
            student_count=200,
            per_student_rate=D("55000.00"),
            total_before_vat=D("11000000.00"),
            vat_amount=D("825000.00"),
        )
    )

    assert lines == [
        "Period: Year 1 Term 2",
        "Students: 200",
        "Rate per student: NGN 55000.00",
        "Subtotal: NGN 11000000.00",
        "VAT (7.5%): NGN 825000.00",
    ]


def test_an_invoice_with_no_breakdown_renders_no_working() -> None:
    from nevo.api.billing import _invoice_working
    from nevo.db.models.billing import Invoice

    assert _invoice_working(Invoice(currency=PricingCurrency.NGN)) == []
