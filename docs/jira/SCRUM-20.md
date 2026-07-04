# SCRUM-20: Parent accounts and consent collection

## Derived acceptance criteria

The Jira ticket did not contain a separate acceptance-criteria section. The
following contract is derived from D.7b and D.1b in its description:

1. Parent links store student, optional parent account, name, contact, contact
   method, and account-created state.
2. Parent links, students, parent stubs, and administrative actions remain
   school-scoped.
3. School-collected consent records the student, consent types, confirming
   administrator, method, source, and timestamp.
4. Direct parent consent issues a single-use, seven-day opaque token and stores
   only its digest.
5. Email/SMS notification details are queued atomically with the invitation.
6. Completing direct consent creates or links an invited parent account stub
   and confirms every consent type in the invitation.
7. Reused, revoked, or expired links cannot confirm consent.
8. Roster-sync-created students receive pending data-processing consent.
9. Students can query their consent gate, and downstream learning endpoints
   can depend on a reusable blocking guard.
10. Database constraints distinguish school and parent confirmation paths.
11. Unit, API, migration, model-contract, and PostgreSQL integration tests
    cover the full flow.

## API surface

- `POST /api/v1/consents/school-confirmations`
- `POST /api/v1/students/{student_id}/parent-consent-requests`
- `POST /api/v1/consents/parent/complete`
- `GET /api/v1/students/{student_id}/parent-links`
- `GET /api/v1/students/me/consent-gate`

## Assumptions

- SENCo-scoped staff own consent administration.
- `data_processing` is the consent required by the learning gate.
- Parent account credential setup is not part of this ticket.
- Notification delivery workers consume the transactional outbox; API callers
  receive `queued`, not a false delivery confirmation.
