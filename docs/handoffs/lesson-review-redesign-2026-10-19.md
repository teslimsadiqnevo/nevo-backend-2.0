# Lesson review redesign: staged backend contract

19 October 2026. Branch: `codex/lesson-review-redesign`.

**Do not merge or deploy before the demo.** Migration 0109 is tested locally only,
not applied to production. No frontend changes are included. This supersedes the
earlier permanent no-bank waiver and does not change the order of engine work.

## Four new routes

All paths below start with `/api/v1/lessons/{lessonId}`. Teacher, SENCo/admin
review permissions and school isolation apply on the server.

1. `POST /key-points/approve-all`
2. `POST /rewrites/approve-all`
3. `PUT /segments/{segmentId}/key-point`
4. `PATCH /segments/{segmentId}/rewrites/{variant}`

The existing `GET /review` now returns the typed hashes, approval records,
missing-key-point segment IDs, rewrite counts and `reviewComplete`.
An OpenAPI subset with these five reads/writes and all referenced schemas is
provided alongside this handoff as `lesson-review-redesign.openapi.json`, so
Olayinka can generate types against the branch before deployment.

### Bulk approval

Read `/review`, then send one request for the entire set:

```json
{"expectedContentHash": "the-64-character-hash-returned-by-the-review-read"}
```

For key points use `keyPointsContentHash`; for rewrites use `rewritesContentHash`.
This is a content revision check, not a per-item loop. A changed lesson returns
409 `review_content_changed`; refresh and let the teacher inspect the new version.
Both requests return the complete `LessonReviewResponse`.

`keyPointApproval` and `rewriteApproval` carry:

```json
{
  "id": "approval-record-uuid",
  "kind": "key_points",
  "approvedBy": "staff-user-uuid",
  "approvedByName": "the approving professional's recorded name",
  "approvedAt": "ISO-8601 timestamp",
  "contentHash": "approved-content-hash",
  "current": true
}
```

The database retains the signed material snapshot and approver name, not just a
boolean on the lesson. Reloading retains the record. Repeating the same person's
approval of unchanged material reuses that act; another person's explicit sign-off
creates their own record. Source/material edits make the previous record
`current: false`; history is preserved rather than overwritten.

Bulk key-point approval refuses 409 `key_point_decision_required` until every
section without an extracted point has an explicit add/omit decision. Removed
points remain omitted; approval never restores them. Empty/processing lessons
return 409 `lesson_not_ready_for_review`.

Bulk rewrites approves all existing simplified and expanded versions together.
It generates no text and returns 409 `no_rewrites_to_approve` if none exist. It
does not quietly approve unrelated media/segment warnings.

Use the two current approval records and `reviewComplete` on the final review
step. A lesson with no rewrites needs no rewrite sign-off. The existing
`readyToAssign` and assignment gates retain their legacy meaning; they are not
a replacement for the redesigned review's sign-off state. This patch does not
retroactively revoke every legacy lesson approval. Existing per-item approval
routes are deprecated compatibility endpoints, not the redesigned UI contract;
the new frontend must use the two lesson-wide acts. Their final removal requires
the coordinated post-demo frontend cutover.

### Missing key point: add or explicitly omit

```json
{"action": "add", "text": "Five equal fifths make one whole."}
```

or:

```json
{"action": "omit"}
```

Both choices create/update a persistent decision row, recording the professional
and time. An omitted point stays absent after reload. A teacher-authored point
keeps `extractedText: ""` rather than claiming the parser found it; its wording
is stored separately and written through to the lesson's key points. Repeating
or changing an explicit missing-point decision does not create duplicate points.
Existing extracted points use their existing amendment/removal routes; this
route returns 409 `key_point_already_exists` rather than overwriting them.
Blank add text is rejected. The lesson-wide sign-off is a separate act.

### Rewrite wording

`variant` is `simplified` or `expanded`.

```json
{"body": "The teacher's replacement wording."}
```

Original wording is preserved as `originalBody`, with `editedBy` and `editedAt`.
Changed wording is pending and is not delivered to students until bulk approval.
The prior approval remains visible but stale. An unchanged save does not revoke
approval. Missing rewrites return 404; this route edits, not generates. Reload the
lesson detail to read the persisted body and its typed edit provenance.

## No-bank ruling

The clarification is retained: **one completed subject satisfies module 4**.
All three earlier modules remain required, and with an available eligible bank
the domain probe remains required before lessons. No new per-subject onboarding
requirement has been introduced.

While no eligible enrolled subject has active questions, module 4 can return
`completed: true, status: "unavailable"` for routing. Subject entries now also
carry `placementStatus: "unestablished"`. The stored status says
`unestablished` / `no_question_bank`; there is no invented subject placement.
The internal conservative prior remains 0.15 (not a midpoint), and mastery seed
provenance says `unestablished_conservative` rather than implying measurement.

When an eligible bank becomes available, the next onboarding read or lesson-entry
check retires that waiver, preserves the first three completions, and returns
`nextModule: "domain_probe"`. Lesson entry returns the existing 409
`onboarding_required` until one subject's probe completes. The app should open
module 4; the backend cannot administer the activity without the student's input.
An existing genuine completed probe is not revoked, and decline-only completion
does not invent a measured placement. No fabricated results are backfilled.

This changed behaviour is staged alongside the redesign, not deployed before the
demo. It replaces the 18 October wording that the waiver was permanent.

## Release and verification

- Migration `20261019_0109` adds `lesson_review_signoffs`; no historical approvals
  are invented. Apply it only to the staging/feature environment now and production
  after the agreed demo hold is lifted.
- 202 selected tests passed. Local HTTP/Postgres checks cover add/omit/reload, stale hashes, repeat sign-offs,
  rewrite editing/reapproval, original-text preservation, school/role refusal,
  73-section bulk approval, and bank arrival reopening module 4 only.
- Migration upgrade and downgrade were exercised only on disposable local
  PostgreSQL. Ruff passed. The existing Starlette/httpx deprecation warning remains.
- Frontend and production data are untouched. Production still uses main and 0108.
