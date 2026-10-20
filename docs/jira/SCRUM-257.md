# SCRUM-257: confirmed consent for student processing

Implemented on main, 20 October 2026. This supersedes the earlier policy that only withdrawal blocked learning.

## Contract

| Stored processing-consent state | Learning processing | Response |
| --- | --- | --- |
| confirmed | permitted, subject to existing authorisation | normal route response |
| pending, not_sent, missing | refused | 403 consent_required |
| withdrawn | refused | 403 consent_withdrawn |
| lookup unavailable | refused | 503 consent_service_unavailable |

`GET /api/v1/students/me/consent-gate` remains available. `granted` is true only for confirmed consent; `blocked` is its inverse. No payload keys were renamed. Schools must record genuine consent through existing consent workflows. No consent is inferred or auto-confirmed by this change.

## Enforcement

The central ConsentService and StudentLearningConsent dependency cover lesson entry, attempts, progress, Student Ask Nevo, baseline/probe/warm-up, adaptation/review and offline operations. Signal ingestion invokes the same service before accepting a batch. Lesson-detail reads and the offline ZIP route also enforce consent before personalising/delivering the lesson. Non-student actors retain their own permissions; they are not required to have a pupil consent record for their own accounts.

Post-lesson processing rechecks the database before stages. Without confirmation the job becomes `consent_blocked`, with a 15-minute eligibility recheck rather than consuming failure retries. Confirmation allows the job to resume. These checks do not claim to rewind a stage that already finished before a subsequent consent change.

Tests use real HTTP routes and disposable PostgreSQL learning records, the real consent service, all four stored states plus a missing record, service failure and a missing service. They assert that refusals leave no new lesson sessions, answers or progress and do not invoke ingestion or Ask Nevo. Confirmed-consent success and later withdrawal with the same signed-in session are covered. A queued-work test covers suspension and resumption after a valid confirmed record.

No database migration or frontend edit is needed. Deployment of the new application code is required. Existing unconfirmed learners will be blocked; this is the intended change, not a reason to fabricate consent or bypass the gate.

Verification: 273 focused tests passed, including HTTP refusals for guided answers,
scaffold receipts and Ask Nevo helpfulness as well as the primary learning writes.
This server gate cannot recall a lesson already downloaded onto a device; offline
client enforcement and local purge remain frontend-owned.
