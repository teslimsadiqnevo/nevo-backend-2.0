# Admin console backend asks resolved

Source: `Nevo-admin-asks-Backend-Teslim-2026-10-07.pdf`.

## Launch items

1. Admin access can be paused and restored with
   `POST /api/v1/admin/team/{userId}/deactivate` and `/restore`. The caller
   cannot pause themselves or the school's last active oversight admin. Active
   sessions are revoked on pause.
2. `admissionNumber` is on student list, detail and teacher class-roster rows.
3. `GET /api/v1/students/sign-in-details` returns printable Student IDs,
   school code and class context. It supports `classId` filtering.
4. `GET /api/billing/invoices/{invoiceId}/bank-transfer-details` returns the
   invoice number as the exact transfer reference.
5. A school reports a transfer through
   `POST /api/billing/payments/transfer-report`; this never marks an invoice
   paid. Only Nevo finance confirms it through `/manual-transfer`, protected
   by `X-Nevo-Finance-Key` and `BILLING_FINANCE_CONFIRMATION_KEY`.
   `GET /api/billing/payments/transfer-reports` shows the school's reported
   transfers and whether finance has confirmed them.
6. `GET /api/v1/school/dpa-agreement` returns the agreement version and the
   school's name, address and contract dates.
7. The E2E seed now records acceptance of DPA version `2026-10`.
8. Teacher detail returns `subjects`.
9. Assigned-class and assigned-teacher rows return `subjectId` and `subject`.
10. Teacher subjects now support safe reads and appends with GET and POST;
    PUT remains the explicit replace operation.
11. Onboarding returns `subjectSpellingQuestions` and `teachersFound`.
12. A wrong current password returns HTTP 401 with
    `detail.code=current_password_incorrect`.
13. Migration 0094 converts legacy indefinite retention to 365 days. The
    daily retention job already enforces each school's configured window.
14. Consent completion explicitly returns `parentAccountCreated=true` and
    `parentAccountReady=false`; verification or password setup makes it ready.
15. Revoked teachers can be restored with
    `POST /api/v1/teachers/{teacherId}/restore`.
16. Transfer details and reporting work for any invoice id, including older
    overdue invoices.

## Additional screen contracts

- Invitations now carry `classId`, `createdAt`, typed status, one-based bulk
  row metadata and the rejected value. Teacher is the default invite role.
- Expired, revoked, used and invalid join links have distinct response codes.
- Admin team rows expose `founding` and `lastActiveAt`; teacher reads expose
  `classCount` and `lastActiveAt`.
- School overview exposes a stated period and per-class activity recency.
- `GET /api/v1/accommodations` provides the school-wide current accommodation
  read for authorised learning-support users.
- Upcoming billing returns `daysOverdue` and typed `lineItems`.
- Adaptation-log rows expose typed `before` and `after` values.
- Compliance PDFs never contain finding terms or record ids.
- Notifications accept `q` search.
- Public school lookup by sign-in slug is available at
  `GET /api/v1/schools/by-slug/{schoolSlug}`.
- School detail exposes `schoolType`, `foundingPartner` and `adminSeatLimit`.

## Deliberately not invented

These non-launch items need a separate product, legal or commercial contract
before implementation: year-end promotion rules and seven-day undo semantics;
two-step sign-in and recovery-code policy; the authoritative subprocessor
register; objective/report export formats; multiple billing-contact ownership;
per-student immediate billing; and the legal body text of the DPA beyond the
versioned school-specific metadata now served by the backend.
