# Media review, withdrawal and child availability

Backend-only follow-up to SCRUM-255, SCRUM-280/281, SCRUM-286 and SCRUM-287.

## Review

- GET `/api/v1/lessons/{lessonId}/review` now includes `media`: section-linked items, `kind: image | audio`, preparation counts and approval records.
- POST `/api/v1/lessons/{lessonId}/key-points/approve-all` accepts `{expectedContentHash}` from `keyPointsContentHash`. This first review step atomically approves the key points and the ready, safety-cleared media in that exact review snapshot.
- New arrivals are never implicitly approved. A changed snapshot returns 409 `review_content_changed`. An individual source change prevents approval.
- The response includes `keyPointApproval` with the professional's name, ID, timestamp, content hash and current flag; each media item also carries its own named approval.
- The held review routes are now available on main, including bulk rewrite approval and missing-key-point add/omit. Rewrite edits undergo the mandatory content safety check before saving.
- Safety-blocked generation is absent from media lists, review lists and preparation counts. Direct approve/retry/withdraw attempts return 404. Technical generation failures remain visible as recoverable failures, without an asset.

## Withdraw one asset

- POST `/api/v1/lessons/{lessonId}/media/{mediaId}/withdraw` has no body.
- Legacy media without a preparation ID can use POST `/api/v1/lessons/{lessonId}/segments/{segmentId}/media/{kind}/withdraw`, where kind is `image` or `audio`.
- Staff-only, same-school. Returns the media item with `status: withdrawn`, `withdrawnBy`, `withdrawnByName` and `withdrawnAt`; `asset` is null.
- Repeated withdrawal preserves the original actor and timestamp. Withdrawn media cannot be retried or re-approved. No generation is scheduled and review is not restarted.
- Only the selected asset is detached. Audio withdrawal also detaches that section's calculation-step narration. Remaining formats, including text alone, stay available.
- Sitting state, cursor, answers and stored choices are not rewritten. Subsequent reads filter unavailable choices and recommendations. The player should preserve work when refreshing availability; already-downloaded files cannot be recalled by an HTTP response.

## One availability source

Student lesson reads, offline packages, preference validation, adaptation plans and re-teaching routes use the same availability calculation. While SCRUM-280's safety-line renderer is unavailable, activities carrying a safety warning are excluded from student payloads and interactive offers. Teacher reads retain the full activity and warning. Calculation scaffolds remain separate from these practical activities.

Persisted re-teaching alternatives are re-filtered on read, so an asset withdrawn mid-sitting is no longer offered. No cursor reset is involved.

## Break decline

A break offer persists until it is taken or declined. A decline removes the persisted offer and suppresses another offer for two minutes. The manual break control remains available.

## Deployment

Migration `20261023_0115` adds withdrawal audit fields and brings the held lesson-review signoff table onto main. It was applied to the configured shared Supabase database. The backend code still requires deployment on Render.

## Local HTTP verification

Using isolated synthetic lesson records and existing cached media, verified teacher/student authentication; safety-blocked entries absent from lists/counts and refused by approval/retry; student withdrawal refused; stale review hash refused; first-step bulk approval publishes image and narration together with named records; individual image/audio and legacy withdrawal; idempotent withdrawal; retry refused after withdrawal; existing review signoff retained; student text-only fallback; mid-sitting state unchanged; unavailable format choice refused; engine/offline activity suppression; persistent frustration-triggered break offer; and real break-decline ingestion followed by dismissal. Synthetic assignments were cancelled afterwards. No frontend files or test files were added or edited, and no fresh provider generation was required.
