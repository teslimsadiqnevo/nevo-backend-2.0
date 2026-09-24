"""What adding a student mid-term costs, and what actually happens to it.

The quote carried one ``amount`` with no description, so a screen showing a
rate, a VAT line and a total had to do the arithmetic itself - which is the
thing PricingResponse exists to prevent. And a design drew a button reading
"Add Zainab & charge N59,125" against a backend where nothing charges
anything: enrolling a student has no billing side effect at all.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from nevo.api.onboarding import _current_term_label
from nevo.db.models.account import School
from nevo.main import app


@pytest.fixture(scope="module")
def quote_schema() -> dict:
    return app.openapi()["components"]["schemas"]["AdditionQuote"]["properties"]


def school_with(term_starts: list[str] | None) -> School:
    return School(
        name="Test School",
        academic_config={} if term_starts is None else {"term_start_dates": term_starts},
    )


def test_the_client_never_has_to_compute_vat(quote_schema: dict) -> None:
    # The same four the pricing sheet gives, from the same pricing function.
    for field in ("totalBeforeVat", "vatRate", "vatAmount", "totalWithVat"):
        assert field in quote_schema


def test_the_old_total_is_still_there_and_says_what_it_is(quote_schema: dict) -> None:
    # It equalled totalWithVat all along and said nothing about VAT.
    assert "amount" in quote_schema
    assert "totalWithVat" in quote_schema["amount"]["description"]


def test_the_response_says_nothing_is_charged_now(quote_schema: dict) -> None:
    """The field that stops a button promising a charge."""

    assert quote_schema["billed"]["const"] == "next_invoice"


TERMS = ["2026-09-14", "2027-01-11", "2027-04-19"]


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 1), "Term 1 · 2026/2027"),
        (date(2027, 2, 1), "Term 2 · 2026/2027"),
        (date(2027, 5, 1), "Term 3 · 2026/2027"),
        # Before the first term has begun, it is still the first.
        (date(2026, 9, 1), "Term 1 · 2026/2027"),
    ],
)
def test_the_term_is_named_the_way_a_school_names_it(today: date, expected: str) -> None:
    assert _current_term_label(school_with(TERMS), today) == expected


def test_a_school_with_no_term_dates_gets_no_term_rather_than_a_guess() -> None:
    # Printing an invented term on a price is worse than printing none.
    assert _current_term_label(school_with(None), date(2027, 2, 1)) is None
    assert _current_term_label(school_with([]), date(2027, 2, 1)) is None
    assert _current_term_label(school_with(["not-a-date"]), date(2027, 2, 1)) is None


def test_enrolling_a_student_has_no_billing_side_effect() -> None:
    """Stated as a test because a screen was about to promise otherwise."""

    import inspect

    from nevo.api.product_admin import enroll_student

    source = inspect.getsource(enroll_student)

    for word in ("Invoice", "invoice", "charge", "payment"):
        assert word not in source


def test_the_quote_is_not_prorated() -> None:
    """It is a whole term's price for that student, not this term's remainder."""

    from nevo.billing.service import quote_per_student
    from nevo.domain.billing.vocabulary import PricingPlan, RateType

    one = quote_per_student(
        plan=PricingPlan.PER_TERM,
        student_count=1,
        rate_type=RateType.STANDARD,
        per_student_rate=Decimal("1000.00"),
    )

    assert one.total_before_vat == Decimal("1000.00")


def test_the_school_can_record_a_date_of_birth_when_it_enrols() -> None:
    enroll = app.openapi()["components"]["schemas"]["StudentEnroll"]["properties"]

    assert "dateOfBirth" in enroll
    # Optional: a school office mid-term may not have it, and refusing the
    # enrolment over it would keep a child out of lessons.
    assert "null" in str(enroll["dateOfBirth"])
