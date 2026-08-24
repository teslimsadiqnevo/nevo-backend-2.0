from decimal import Decimal

from nevo.billing.service import quote_annual_invoice
from nevo.domain.billing.vocabulary import PricingCurrency, SubscriptionTier


def test_founding_partner_invoice_quote_shows_vat_separately_in_usd() -> None:
    quote = quote_annual_invoice(
        tier=SubscriptionTier.BOUTIQUE,
        is_founding_partner=True,
        year_index=1,
        billed_currency=PricingCurrency.USD,
    )

    assert quote.amount_usd == Decimal("40000.00")
    assert quote.applied_discount_percent == Decimal("37.50")
    assert quote.net_amount_usd == Decimal("25000.00")
    assert quote.vat_amount_usd == Decimal("1875.00")
    assert quote.total_with_vat_usd == Decimal("26875.00")
    assert quote.total_billed_local == Decimal("26875.00")


def test_naira_invoice_quote_applies_fx_buffer_after_vat() -> None:
    quote = quote_annual_invoice(
        tier=SubscriptionTier.MID_MARKET,
        is_founding_partner=True,
        year_index=4,
        billed_currency=PricingCurrency.NGN,
        fx_rate=Decimal("1500.000000"),
    )

    assert quote.applied_discount_percent == Decimal("20.00")
    assert quote.net_amount_usd == Decimal("64000.00")
    assert quote.vat_amount_usd == Decimal("4800.00")
    assert quote.total_with_vat_usd == Decimal("68800.00")
    assert quote.fx_rate_applied == Decimal("1575.000000")
    assert quote.total_billed_local == Decimal("108360000.00")
