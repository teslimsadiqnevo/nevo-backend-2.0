"""Invoice issuance: the right periods, priced per student, exactly once."""
from datetime import date

from nevo.billing.issuance import InvoiceIssuanceService
from nevo.domain.billing.vocabulary import PricingPlan

CODE = "lagos-01"


def periods(plan: PricingPlan, **kwargs):  # type: ignore[no-untyped-def]
    return InvoiceIssuanceService.periods_for(
        plan=plan,
        school_code=CODE,
        contract_start=kwargs.pop("contract_start", date(2026, 9, 1)),
        year_index=kwargs.pop("year_index", 1),
        **kwargs,
    )


def test_an_annual_school_is_invoiced_once_a_contract_year() -> None:
    result = periods(PricingPlan.ANNUAL, year_index=2)

    assert len(result) == 1
    assert result[0].number == "NEVO-LAGOS01-Y2"
    assert result[0].label == "Year 2"
    assert result[0].starts_on == date(2027, 9, 1)


def test_a_per_term_school_is_invoiced_three_times_a_contract_year() -> None:
    result = periods(PricingPlan.PER_TERM)

    assert [item.number for item in result] == [
        "NEVO-LAGOS01-Y1T1",
        "NEVO-LAGOS01-Y1T2",
        "NEVO-LAGOS01-Y1T3",
    ]
    assert [item.label for item in result] == [
        "Year 1 Term 1",
        "Year 1 Term 2",
        "Year 1 Term 3",
    ]


def test_a_school_with_its_own_calendar_is_billed_on_its_own_terms() -> None:
    configured = (date(2026, 9, 8), date(2027, 1, 12), date(2027, 4, 20))

    result = periods(PricingPlan.PER_TERM, term_start_dates=configured)

    assert tuple(item.starts_on for item in result) == configured


def test_a_school_without_a_calendar_falls_back_to_an_even_split() -> None:
    result = periods(PricingPlan.PER_TERM, contract_start=date(2026, 9, 1))

    assert [item.starts_on for item in result] == [
        date(2026, 9, 1),
        date(2026, 12, 31),
        date(2027, 5, 1),
    ]


def test_a_partial_calendar_is_ignored_rather_than_half_applied() -> None:
    result = periods(
        PricingPlan.PER_TERM,
        term_start_dates=(date(2026, 9, 8), date(2027, 1, 12)),
    )

    assert result[0].starts_on == date(2026, 9, 1)


def test_annual_and_per_term_invoice_numbers_cannot_collide() -> None:
    annual = {item.number for item in periods(PricingPlan.ANNUAL)}
    per_term = {item.number for item in periods(PricingPlan.PER_TERM)}

    assert not annual & per_term


def test_invoice_numbers_are_deterministic() -> None:
    assert InvoiceIssuanceService._invoice_number("lagos-01", 2) == "NEVO-LAGOS01-Y2"
    assert (
        InvoiceIssuanceService._invoice_number("lagos-01", 2, term=3) == "NEVO-LAGOS01-Y2T3"
    )


def test_first_contract_year_starts_on_the_contract_start_date() -> None:
    start = date(2026, 9, 1)

    assert InvoiceIssuanceService._period_start(start, 1) == start


def test_later_contract_years_start_a_year_apart() -> None:
    start = date(2026, 9, 1)

    assert InvoiceIssuanceService._period_start(start, 2) == date(2027, 9, 1)
    assert InvoiceIssuanceService._period_start(start, 3) == date(2028, 8, 31)
