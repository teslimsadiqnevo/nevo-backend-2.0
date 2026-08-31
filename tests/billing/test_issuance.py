"""Invoice issuance tests."""
from datetime import date

from nevo.billing.issuance import InvoiceIssuanceService


def test_invoice_numbers_are_deterministic_per_contract_year() -> None:
    number = InvoiceIssuanceService._invoice_number("lagos-01", 2)

    assert number == "NEVO-LAGOS01-Y2"
    assert InvoiceIssuanceService._invoice_number("lagos-01", 2) == number


def test_invoice_numbers_differ_between_contract_years() -> None:
    first = InvoiceIssuanceService._invoice_number("lagos-01", 1)
    second = InvoiceIssuanceService._invoice_number("lagos-01", 2)

    assert first != second


def test_first_contract_year_starts_on_the_contract_start_date() -> None:
    start = date(2026, 9, 1)

    assert InvoiceIssuanceService._period_start(start, 1) == start


def test_later_contract_years_start_a_year_apart() -> None:
    start = date(2026, 9, 1)

    assert InvoiceIssuanceService._period_start(start, 2) == date(2027, 9, 1)
    assert InvoiceIssuanceService._period_start(start, 3) == date(2028, 8, 31)
