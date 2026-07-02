# SCRUM-16: Core database tables — schools, users, classes, enrollments, consent

## Scope

Create the canonical PostgreSQL schema for accounts and school structure that the
rest of the platform builds on. Per Backend Architecture Section 2 and Product
Architecture A.2.

## Acceptance criteria

1. `schools` stores each institution with `school_code`, `school_url_slug`,
   `auth_method`, `enrollment_band`, founding-partner status, price-lock expiry,
   and data-retention window.
2. `users` stores every account with a `role`, `auth_method`, credential hashes
   (`password_hash`, `pin_hash`), `sso_external_id`, `is_first_use`, and a
   `status` with `deactivated_at`.
3. `classes` belong to a school; `student_class_enrollments` link students to
   classes and cannot duplicate a (student, class) pair.
4. `consent_records` track per-subject consent with a `pending`/`confirmed`
   status, the confirming admin, and the confirmation method.
5. Controlled values are enforced by PostgreSQL enums; numeric and state
   invariants are enforced by check constraints.
6. `deactivated_at` is set if and only if a user's `status` is `deactivated`.
7. A consent record's confirmation fields are all present if and only if its
   `status` is `confirmed`.
8. The SCRUM-15 deferred dependency is closed: both learner profile tables gain
   the `learner_id -> users.id` foreign key.
9. No table, column, constraint, index, or enum value contains prohibited
   diagnostic terminology (Zero-Tag contract).
10. Alembic can upgrade a clean PostgreSQL database to `head` and downgrade it to
    `base`.
11. Automated contract tests and PostgreSQL integration tests pass in CI.

## Enums

- `user_role`: `student`, `teacher`, `senco_admin`, `other_admin`
- `auth_method`: `email_password`, `pin`, `sso`
- `user_status`: `active`, `invited`, `deactivated`
- `school_enrollment_band`: `small`, `medium`, `large`, `very_large`
- `consent_status`: `pending`, `confirmed`
- `consent_type`: `data_processing`, `camera`, `offline_storage`
- `consent_confirmed_via`: `written`, `verbal`, `email`, `digital`

## Assumptions to confirm in review

The ticket names these columns but does not fix their controlled values or
defaults. The following were chosen from the legacy backend and general UK SEN
context and should be reconciled with Backend Architecture Section 2:

- `school_enrollment_band` tier names (used named sizes, not fixed boundaries).
- `data_retention_days` default of `365`.
- `consent_type` and `consent_confirmed_via` value sets.
- `users.role` set (four roles, matching SCRUM-17 session-timeout roles).
  Parent/guardian accounts are owned by SCRUM-20 and are not added here.

## Downstream dependencies

- SCRUM-17 (Auth Service) reads `users` (`role`, `auth_method`, `pin_hash`,
  `status`) and enforces role-based session timeouts.
- SCRUM-18 (permissions) builds role scopes on top of `user_role`.
- SCRUM-19 owns teacher-class assignment; `classes` here intentionally carries no
  teacher column yet.
- SCRUM-20 owns parent/guardian accounts and the consent collection workflow.
