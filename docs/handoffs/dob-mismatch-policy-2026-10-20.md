# DOB mismatch: backend handoff

## Implemented policy

- A known DOB mismatch holds sign-in, provisioning, existing bearer sessions and student-entry PIN activation. Consent confirmation does not override the hold. The post-lesson worker also waits rather than inferring during a hold.
- The enrolled class/year-group maps to the existing early-primary, upper-primary, junior-secondary or senior-secondary age band. Missing, unrecognised or conflicting bands fail closed; no range is invented. These are the existing schooling bands, not a one-year birthday tolerance.
- Pending resolution, the operative account DOB is the later of the two dates, representing the younger age. Both source dates remain separately recorded. No date is marked agreed while held.
- A school administrator explicitly rechecks the admissions date. A linked parent then supplies the DOB again. The parent's date becomes operative only when both checks exist, the gap is at most two calendar years, and both dates fit the enrolled band. Exactly two years is permitted; two years plus one day is not.
- A routine roster correction, consent submission, school-only action or generic account activation cannot substitute for the two adult checks. There is no force-approve endpoint. Any fresh discrepancy after resolution starts a new hold cycle.
- The new endpoints collect only a date. Unknown request fields are refused; identity-document upload is neither requested nor supported.

## Frontend contract (no frontend files changed)

- `GET /api/v1/age-checks`: school-admin queue.
- `GET /api/v1/age-checks/parent`: checks for the authenticated parent's linked children.
- `POST /api/v1/age-checks/{id}/school-recheck`: school-admin-only, body `{"dateOfBirth":"2016-01-01"}`.
- `POST /api/v1/age-checks/{id}/parent-reconfirm`: linked-parent-only, same body, only after school recheck.
- Responses include `blocksAccess`, `enrolledAgeBand`, `holdReasons`, `schoolNotifiedAt`, `deletionDueAt`, `schoolRecheckedAt` and `parentReconfirmedAt`. Parent DOB is not returned to staff.
- Hold reasons: `date_missing`, `enrolled_age_band_unavailable`, `date_gap_exceeds_two_years`, `outside_enrolled_age_band`, `reconfirmation_required`.
- Refusals: 403 unauthorised role; 404 `age_check_not_found`; 409 `school_recheck_required` or `age_check_not_pending`; 410 `age_check_expired`; 422 invalid/future dates or extra request fields.
- Student-entry reads now report `ageCheckPending: true` and `accountReady: false` during a hold. PIN activation returns 403 `age_check_pending`. Ordinary credential login remains a generic authentication refusal; existing-token validation returns 401 `account_paused`.
- A hard exception returns the check with `blocksAccess: true`; HTTP 200 on recording an adult's date does not mean the account was released.

## Notification and deletion

The initial mismatch writes a durable school-admin inbox notification using the existing `consent_action_required` type and the pupil's admin record link. `schoolNotifiedAt` is the time that notification is committed, not when the mismatch was created or when a reminder is sent. Email delivery uses the existing notification worker; the clock does not claim successful email delivery.

No active school administrator means no notification timestamp and no new 30-day deletion clock. The account stays held and the hourly sweep retries notification. A school recheck or failed parent reconfirmation does not reset the original deadline.

At 30 days, further reconciliation is refused. The existing hourly retention sweep performs the linked-record and managed-file purge. Database triggers preserve the earlier of this deadline and any existing purpose-ended deadline. Storage failures leave the purge retryable; they are not reported as completed erasure.

Purging removes the school roster association, class enrolments, parent links, DOB-check record and learner-owned data including signal events. As in the retention implementation, an identity-cleared, school-detached account stub and minimal erasure receipt remain; this is not a claim that every `users` row is physically deleted. Infrastructure backups are outside this worker.

## Deployment and verification

Deploy backend code with migration `20261020_0111` (`alembic upgrade head`). The migration reassesses legacy checks against enrolled bands, holds disagreements and out-of-band records, and does not fabricate historical school-notification dates. The hourly worker notifies those schools and starts each clock then.

Verified on disposable local PostgreSQL only: 156 consent/auth/retention and related checks passed, including 11 new calendar-boundary, HTTP authorisation/reconfirmation, bearer-session, notification-clock and real linked-data erasure checks. Fresh-database migration to 0111 also passed.

Two motor-baseline tests in `test_remaining_jira_contracts.py` fail identically in an unchanged checkout of the previous main; those unrelated failures were not hidden or modified as part of this DOB change. This handoff is not a production-deployment or production-erasure certificate.
