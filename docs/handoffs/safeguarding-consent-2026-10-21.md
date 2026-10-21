# SCRUM-258 and SCRUM-261

## Before changes

GET /api/v1/safety/events already exists, with pending_only, limit and before filters. POST /api/v1/safety/events/{id}/acknowledge already exists and preserves the first actor and timestamp on repeat requests. Both were SENCo-role-only rather than Learning Support grant-gated. Entries returned id, studentId, phase, action, categories, policyVersion, createdAt, acknowledgedAt and acknowledgedBy. Acknowledgement only marked the entry: it did not appear on the profile. There is no resolve or close operation.

The event table has no conversation ID or question/response text. Ask Nevo transcript reads are scoped to the requesting actor, not school membership or Learning Support. Staff do not gain a child's transcript through the safeguarding routes.

Confirmed consent is already required on main. Pending is refused, but previously shared consent_required. The production read-only snapshot on 21 October found zero signal rows belonging to currently pending data-processing consent records, and zero schools with active students but no active Learning Support holder. This is not a historical ingress count: stored event timestamps and current consent records cannot establish consent status at receipt.

## Operational confirmations

Yinka must confirm provider backup overwrite cycles, security/access-log retention, Vercel region, and the human safeguarding owner, response time and school-notification procedure. API implementation and automated checks do not establish those operational facts.

## Implemented contract

- Pending consent now returns HTTP 403 with detail.code=consent_pending. Missing remains consent_required, withdrawn remains consent_withdrawn, and an unavailable gate remains HTTP 503. Only confirmed consent permits collection. The shared consent gate applies the pending code consistently to its other callers too.
- Both safeguarding routes require an explicit current Learning Support grant. A SENCo title alone is insufficient. A class teacher without that grant is refused, even for their own pupil. Teachers explicitly appointed as Learning Support holders retain their grant-based access; the privilege comes from the grant, not class membership.
- The list is school-wide for holders and includes only child-associated block/safeguard entries, not adult content-upload checks. Existing metadata fields remain compatible. studentName and acknowledgedByName are added; no child questions, response bodies or conversation identifiers are returned.
- Acknowledgement accepts no resolution decision and preserves the first actor and timestamp on repeat requests. GET /api/v1/students/{id}/profile now returns safeguardingAcknowledgements with eventId, acknowledgedAt, acknowledgedBy, acknowledgedByName and a fixed note explicitly saying acknowledgement is not resolution. Only holders receive these lines; ordinary class teachers still receive their permitted profile, with an empty safeguardingAcknowledgements array.
- Names are resolved from the current user records. The persisted acknowledgement identity is the user ID, with its timestamp; this is not a frozen historical name snapshot.
- Active-holder counts exclude inactive or ineligible staff. Grant, handover, revocation and teacher-deactivation guards now share the school-row lock already used by admin deactivation. This prevents concurrent supported API removals from leaving zero holders. The production snapshot found no active-student school needing holder backfill. Direct database edits can bypass API policy and are not presented as protected by a database trigger.
- No new safeguarding queue or resolve/close route was added. Retention endpoint permissions were preserved, not widened by the safeguarding change.

## Verification and release

87 focused tests passed against the disposable local test database, covering consent, safeguarding API access and acknowledgement, holder-removal concurrency, profile visibility, and cross-actor transcript rejection. No production test records were changed. No schema migration is required. These are backend changes; frontend tickets and operational safeguarding coverage still require their owners. Local automated verification is not a claim that the new code is deployed or that the human response service is operating.
