# Admin and Content Backend Blockers Resolved

Date: 7 September 2026

This handoff covers the backend findings in `adminbackendblocker.pdf`,
`nevocontentgap.pdf`, and the school-registration production failure reported by
the frontend team.

## School registration

- `POST /api/v1/schools/register` is fixed and now has a typed
  `SchoolRegistrationResponse`.
- The failure was caused by SQLAlchemy inserting the `admins` row before its
  referenced `users` row. Registration now flushes school, user, and admin in
  dependency order, then writes scopes in the same transaction.
- Failed historical requests did not leave partial schools or users behind.
- A successful registration now creates an unread admin welcome notification.

## Consent and school administration

- Consent lifecycle values are now `not_sent`, `pending`, `confirmed`, and
  `withdrawn`.
- Student list, student detail, and class roster rows now include a typed
  `consent` object with `status`, `actorId`, `actorName`, `timestamp`, and
  `channel`.
- Student invitations expose `consentStatus`. When an invited student joins and
  has parent contact details, the parent consent request is queued automatically.
- Parent withdrawal updates the consent record to `withdrawn`; subsequent
  student reads expose the change and its audit metadata.
- `GET /api/v1/school/narrative` returns an admin-only, live-data summary.
- `GET /api/v1/school/dpa-acceptance` reads the latest typed DPA acceptance.
- `POST /api/v1/school/dpa-acceptance` records the document version, accepting
  administrator, and timestamp. It is idempotent per school and version.
- Admin notification types now cover onboarding, consent, roster sync, invoices,
  and SSO connection attention.
- Billing subscription responses now include `pricingModel`,
  `activeStudentCount`, `perStudentAnnualRate`, and `currency` while preserving
  the signed annual contract value.
- Permission scope enforcement was already active. A token without `oversight`
  receives `403` from `GET /api/v1/admin/team`; the existing test covers this.

## Content and lesson player

- `calculation` is a native content segment type.
- The content prompt now requires at least three useful segments, one valid
  checkpoint with options and answer key, one visual variant, and one audio
  variant across a generated lesson.
- Audio generation now runs before variant normalization, so YarnGPT placeholders
  become stored, playable audio instead of being removed prematurely.
- `availableModalities` now advertises visual or audio only when a usable payload
  exists. Failed generation is marked for teacher review.
- New `POST /api/content/lessons/{lesson_id}/regenerate` rebuilds a legacy lesson
  in place with the current checkpoint and modality contract.
- New learners with a balanced profile can now receive a modality suggestion
  when three aligned signals clear the confidence threshold and a genuine
  alternative modality exists. Rate limits and multi-signal safeguards remain
  enforced.

## Session and error contracts

- New `POST /api/v1/auth/session/refresh` extends an active sliding session and
  returns the updated expiry without interrupting lesson progress.
- Request validation failures now use the documented envelope:
  `detail.code`, `detail.message`, and `detail.errors`.
- Swagger describes the same validation envelope and all new endpoints have
  concrete response models.

## Deployment state

- Supabase migration `20260907_0041` has been applied successfully to the shared
  test database.
- School registration was exercised against Supabase inside a rollback-only
  transaction and created the school, user, admin, notification, and permissions
  successfully.
- The legacy demo lesson must be regenerated after deployment with YarnGPT,
  Supabase Storage, image generation, and image-review credentials configured.
  Call `POST /api/content/lessons/{lesson_id}/regenerate` as a teacher or admin.

## Frontend action

No frontend code was changed. The frontend can consume the new fields and routes
directly from the generated OpenAPI contract. Existing pages should stop joining
or guessing consent state, session renewal, and legacy lesson repair locally.
