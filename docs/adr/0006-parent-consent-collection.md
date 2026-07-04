# ADR 0006: Parent links and consent collection

- Status: Accepted for SCRUM-20
- Date: 2026-07-04
- Owners: Nevo backend team

## Context

Students must not progress into learning delivery until required consent is
confirmed. Consent may be collected by a school administrator or directly from
a parent or guardian. Direct collection also establishes the parent-student
relationship without pretending the parent has completed account setup.

## Decision

- `parent_links` records the school-scoped relationship, parent name, normalized
  contact, contact method, optional parent account, and whether the account
  stub exists.
- `parent_guardian` is a first-class user role. Direct consent creates an
  invited account stub; a later onboarding ticket will own credential setup.
- School confirmation is restricted to the `senco` scope and attributes the
  confirmation to the administering user.
- Direct confirmation uses opaque, single-use, seven-day tokens. Only an HMAC
  digest is stored in `consent_invitations`.
- An invitation can cover multiple consent types through
  `consent_invitation_items`.
- Notification details are written to `consent_notification_outbox` in the same
  transaction as the invitation. A delivery worker can send email or SMS
  without losing requests if a provider is unavailable.
- Consumed invitations clear the raw consent URL from the outbox.
- `consent_records` distinguishes `school` and `parent` confirmation sources
  and enforces the matching confirmer at database level.
- A PostgreSQL trigger creates pending data-processing consent whenever a
  student is inserted through SSO roster sync.
- `ConsentService.require_student_consent` is the reusable B.2 Step 5 gate.

## Consequences

- Consent state is strongly consistent and auditable.
- API responses report notification delivery as queued, never sent
  prematurely.
- Email/SMS provider workers can be added behind the outbox without changing
  consent policy.
- Parent login and profile management remain separate from the account stub
  created here.
