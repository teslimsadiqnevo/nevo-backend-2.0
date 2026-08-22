# Admin dashboard: Billing, invoices, and payment management

Backend contract for the admin billing surface.

## Endpoints

All endpoints require the `billing` permission scope and act on the actor's
school from the permission snapshot.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/billing/subscription` | Current plan, contract, renewal notice, contact, and masked payment method |
| `GET` | `/api/billing/invoices` | Invoice history with `dateFrom`, `dateTo`, and `status` filters |
| `GET` | `/api/billing/upcoming` | Next pending charge and renewal notice |
| `PUT` | `/api/billing/payment-method` | Save masked payment method details and processor reference |
| `PUT` | `/api/billing/billing-contact` | Save finance contact details separate from admin access |

## Schema

`schools` now stores:

- `subscription_tier`
- `contract_value`
- `contract_start`
- `contract_end`
- `billing_contact_id`

New tables:

- `billing_contacts`
- `billing_payment_methods`
- `invoices`

Payment methods store only display-safe fields, last four digits, and an
internal processor reference. Full card numbers, full bank account numbers,
CVV values, and provider secrets are not stored or returned.

## Renewal Notice

The backend returns `renewalBannerVisible` and `renewalMessage` when the
contract end date is within 60 days. The copy is informational, not urgent.

## Invoice PDFs

Invoices have a required `pdf_url`. Invoice issue jobs should generate the PDF
once and store the resulting URL on the invoice row. The admin API is payment
processor agnostic.
