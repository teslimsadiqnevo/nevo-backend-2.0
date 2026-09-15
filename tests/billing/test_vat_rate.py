"""VAT on an invoice: a percentage, stored, and said out loud.

"7.5" and "0.075" are the same rate and differ by 100x on screen, and the
contract said only that vatRate was a number. The invoice also carried the VAT
amount with no rate beside it, so a client had nothing to label the line with
and the PDF hardcoded 7.5% - which would quietly rewrite every historical
invoice the day the government moves the rate.
"""

from __future__ import annotations

from decimal import Decimal

from nevo.api.billing import InvoiceResponse, PricingResponse, _invoice_working
from nevo.billing.service import VAT_RATE


class _Invoice:
    """Only the fields the working lines read."""

    def __init__(self, vat_rate: Decimal | None) -> None:
        self.student_count = 30
        self.per_student_rate = Decimal("150000.00")
        self.total_before_vat = Decimal("4500000.00")
        self.vat_amount = Decimal("337500.00")
        self.period_label = "2026/2027 session"
        self.vat_rate = vat_rate

        class _Currency:
            value = "NGN"

        self.currency = _Currency()


def test_the_rate_is_a_percentage_not_a_fraction() -> None:
    # The service divides by 100 when it applies the rate, so 7.50 means
    # 7.5% - the thing a client renders with a per-cent sign.
    assert VAT_RATE == Decimal("7.50")
    assert VAT_RATE > 1


def test_the_contract_says_which_it_is() -> None:
    # An undocumented number is what sent this question round twice.
    for model, field in ((PricingResponse, "vat_rate"), (InvoiceResponse, "vat_rate")):
        description = model.model_fields[field].description or ""
        assert "percentage" in description.lower(), model
        assert "not a fraction" in description.lower(), model


def test_an_invoice_states_the_rate_it_was_charged_at() -> None:
    lines = _invoice_working(_Invoice(Decimal("7.50")))
    assert "VAT (7.5%): NGN 337500.00" in lines


def test_a_rate_change_does_not_rewrite_an_old_invoice() -> None:
    lines = _invoice_working(_Invoice(Decimal("10.00")))
    assert "VAT (10%): NGN 337500.00" in lines


def test_an_invoice_from_before_the_rate_was_stored_claims_nothing() -> None:
    lines = _invoice_working(_Invoice(None))
    assert "VAT: NGN 337500.00" in lines
    assert not any("%" in line for line in lines)
