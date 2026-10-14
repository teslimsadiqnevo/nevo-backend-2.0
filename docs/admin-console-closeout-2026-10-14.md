# Admin console closeout: 14 October 2026

## B1: SENCo QA account

A verified `senco_admin` account with a recorded Learning Support grant was seeded in the configured Supabase E2E school, code `D6AM`: `senco.e2e@nevolearning.com`. Password is supplied separately, not committed. Live sign-in and `/api/v1/users/me` both returned 200. The existing E2E administrator was not re-roled. The finalisation gate stays SENCo-only.

## B2 and B3: Subject progress

`GET /api/v1/parents/me/children/{studentId}/subject-progress` now returns `masteredSoFar` per subject, computed from that child's current concept mastery records, and nullable `lastLessonAt`, the last lesson-session start timestamp for the subject across all time. Quiet weeks retain this date. No activity means null.

When term dates are absent and no `weekOf` is supplied, the default reporting window begins on the school's setup date and ends today in Lagos. `window.kind` is `since_setup`; otherwise it is `week`. An explicit `weekOf` still asks for that historical week, even without term dates. `window.state` retains `terms_not_set` where applicable.

## B4: Removing a teacher subject

`PUT /api/v1/teachers/{teacherId}/subjects` already refuses a subject with an active class assignment using status 409 and `detail.code: subject_in_use_by_assignment`. Swagger now declares that refusal. Remove the class assignment before removing the subject.

## B5: Escalation pagination

`GET /api/v1/escalations?openOnly=true&limit=50&offset=0` returns only unacknowledged concerns, newest first. `X-Total-Count` is the complete matching count; `X-Has-More` says whether another page remains. Default limit is 50, maximum 200. The JSON array shape is preserved. The count and rows follow the same school/class access rules.

## B6: Found teachers and classes

The onboarding read adds `teacherDetailsFound`, an array of `{ name, email, classes: string[] }`. Rows are grouped by email, so multiple class/subject rows for one teacher become one teacher with their classes. Existing `teachersFound: string[]` is retained for compatibility. Class names reflect current corrections; before commit these are proposed names, not persistent class ids.

## B7: Upcoming charge lines

Upcoming-charge `lineItems` now uses the stored invoice breakdown and currency. The subscription line carries `kind: subscription`, `quantity`, `unitAmount`, and the recorded pre-VAT amount. The VAT line carries `kind: vat`, the recorded VAT amount and nullable `percentageRate` (7.5 means 7.5 percent).

Legacy invoices without a recorded breakdown have an empty list rather than an invented student count, rate or tax split. Their recorded total remains available as `amount`.

## B8: Two-step sign-in

No two-step sign-in backend exists. Settings should continue saying it is unavailable. Whether it is required for launch is a product decision; this patch does not claim it is implemented or decide its launch scope.

## B9: Senior admin reach and demotion

Senior-only operations are `PATCH /api/v1/school`, `POST /api/v1/admin/team/{userId}/promote-senior`, and the new `POST /api/v1/admin/team/{userId}/demote-standard`. Other operations retain their existing scope/role gates; personal preferences are not senior-only.

Demotion requires a senior actor in the same school, preserves the person's explicit scopes and Learning Support grant, and refuses removal of the final active senior with 409 `detail.code: last_senior_admin`. School locking serialises concurrent access-level changes. Promotion of another active administrator provides the way to hand over before self-demotion.

## B10: Class teacher access

Already pushed in `8a7199b`: class teachers can use the standard student profile and mark their own pupils' attention flags seen without Learning Support. A teacher's class assignments are still checked. Learning Support remains required for adaptation history and other support-only reads. The generic grant helper has not been relaxed, since it has no student context and cannot safely enforce an own-class exception. Any further expansion pending P1 needs the product ruling's specific surfaces.

No frontend files changed. No migration is required.
