# Billing Architecture

Implemented the backend foundation for the July 2026 pricing model.

## Pricing Model

- Four seeded annual licence tiers:
  - Boutique: 0-250 pupils, $25,000 founding partner, $40,000 commercial
  - Mid-Market: 251-500 pupils, $50,000 founding partner, $80,000 commercial
  - Premium: 501-800 pupils, $80,000 founding partner, $125,000 commercial
  - Enterprise: 801+ pupils, $140,000 founding partner, $220,000 commercial
- VAT is held separately at 7.5%.
- Naira billing uses the supplied FX rate plus the 5% volatility buffer.

## Schema

- `subscription_tiers`
- `exchange_rates`
- `contracts`
- `step_up_schedules`
- `billing_ledger`
- `schools.payment_source`

Payment sources are represented as `direct`, `sterling`, and `partner`. v1 launch remains direct only; Sterling flows are architecture-only until partnership terms are final.

## Calculation

`quote_annual_invoice()` returns the commercial baseline, applied discount, net licence amount, VAT amount, USD total, applied FX rate, and local billed total.
