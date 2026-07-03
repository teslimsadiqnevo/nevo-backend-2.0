# ADR 0002: Core account, school, and consent schema

- Status: Accepted for SCRUM-16
- Date: 2026-07-02
- Owners: Nevo backend team

## Context

SCRUM-15 created learner profiles but deferred the `learner_id` foreign key
because no canonical `users` table existed. SCRUM-16 introduces the account and
school structure the rest of the platform depends on, and closes that deferral.

## Decision

Five tables model the account domain:

- `schools` — one row per institution. Carries commercial and operational
  attributes: `school_code`, `school_url_slug`, `auth_method`, `enrollment_band`,
  `is_founding_partner`, `price_lock_expiry`, `data_retention_days`.
- `users` — one row per account. `role` and `auth_method` drive downstream
  behaviour; `password_hash`/`pin_hash`/`sso_external_id` support the three
  authentication methods; `status` plus `deactivated_at` model the lifecycle.
- `classes` — belong to a school. No teacher column yet; teacher-class
  assignment is owned by SCRUM-19.
- `student_class_enrollments` — many-to-many between students and classes, unique
  per (student, class).
- `consent_records` — per-subject, per-type consent with an auditable
  confirmation (confirming admin, method, timestamp).

Controlled values use PostgreSQL enums. Two invariants are enforced at the
database level rather than only in application code:

- A user's `deactivated_at` is set if and only if `status = 'deactivated'`.
- A consent record's `confirmed_by_admin_id`, `confirmed_via`, and `confirmed_at`
  are all present if and only if `status = 'confirmed'`.

Foreign keys use `ON DELETE RESTRICT` (matching SCRUM-15), except a class's
enrollments, which `CASCADE` because they are owned by the class.

### Closing the SCRUM-15 deferral

This migration adds `learner_id -> users.id` foreign keys to both
`learner_profiles` and `learner_profile_history`, as ADR 0001 required once the
`users` table existed.

## Zero-Tag compliance

These tables are administrative and contain no functional-profile data. All
identifiers avoid prohibited diagnostic terminology; `senco_admin` refers to the
staff coordinator role and does not encode any learner attribute. The schema
contract test scans every table in the metadata, including these.

## Consequences

- Auth, permissions, and enrollment work (SCRUM-17/18/19) can build on a stable
  account schema.
- Several controlled-value sets are assumptions pending Backend Architecture
  Section 2 (see docs/jira/SCRUM-16.md); changing them later needs a migration.
- Deleting a school or a referenced user is blocked while dependent rows exist,
  which is intentional for auditability.
