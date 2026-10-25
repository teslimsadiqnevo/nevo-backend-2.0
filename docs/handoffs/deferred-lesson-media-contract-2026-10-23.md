# Lesson review and background media: backend handoff

## Behaviour

Lesson parsing, question validation and depth preparation finish before optional image/audio generation. The core lesson and durable media jobs commit together. Optional provider failures no longer prevent review of the core lesson. Existing lesson approval and assignment rules still apply.

No frontend files or automated tests were changed.

## Upload polling

`GET /api/v1/uploads/{id}` retains the existing status/stage fields and adds:

- `reviewReady`: true once status is ready or confirmed; open lesson review then, without waiting for media.
- `mediaPreparation`: phase, generationComplete, images and audio counters.
- Phases: not_requested, preparing, awaiting_review, complete, complete_with_errors.
- Each counter contains total, queued, processing, awaitingReview, approved, failed and stale.

Counters represent section-level media jobs, not physical files. One calculation audio job can produce several step recordings. Upload lists also carry reviewReady; poll the detail for media progress.

## Media review routes

All routes are staff-only and school-scoped:

- `GET /api/v1/lessons/{lessonId}/media`: lessonId, summary and items.
- `POST /api/v1/lessons/{lessonId}/media/{mediaId}/approve`: approve one prepared asset.
- `POST /api/v1/lessons/{lessonId}/media/approve`: atomic approval of explicit IDs, body `{"mediaIds":["uuid"]}`.
- `POST /api/v1/lessons/{lessonId}/media/{mediaId}/retry`: explicitly request a remake of unapproved `awaiting_review`, failed or stale media; source-changed prepared media is refreshed from current lesson content. The new candidate returns to normal teacher review and is never auto-approved.

Items include id, segmentId, kind, status, asset, sourceChanged, failureCode, createdAt, completedAt, approvedAt, approvedBy and approvedByName. Prepared assets are available to staff for review but are not attached to the student lesson until approved. Future arrivals are never implicitly approved. Approval retries preserve the original actor and timestamp.

Source changes invalidate prepared media. Approved assets cannot be overwritten through retry. Generation uses existing media caches; unchanged upload reuse keeps existing jobs. Crash recovery uses leases and bounded attempts, not an exactly-once billing guarantee. Student picture availability is withheld for `practice_question` sections; teaching sections with checks may serve a safety-reviewed picture, with check/answer context provided only to the image reviewer.

409 codes: media_source_changed, media_not_ready, media_safety_review_required, media_retry_not_allowed. Failure codes include provider_not_configured, provider_quota, generation_unavailable and generation_interrupted.

The existing media URL refresh route now checks lesson access and whether an asset is attached/approved for a student, or available for same-school staff review. Unknown assets return 404 media_not_available. This does not change the storage bucket's public/private configuration.

## Verification and deployment

A fresh Seed Germination lesson uploaded through local HTTP became reviewable in 129.2 seconds with four sections while optional media was still preparing. Both lesson-detail routes returned 200. Missing image configuration and YarnGPT quota failures subsequently appeared in media status without blocking the core lesson.

Using an existing same-school, safety-reviewed image, local HTTP checks confirmed: student sees text only before asset approval; text and visual after approval; actor/time persisted; repeated approval is idempotent; student review/approval is refused; source-change approval is refused; failed-job retry and expired-lease recovery work; unknown asset signing is refused. Fresh image generation and successful new narration were not verified, as agreed.

Migration 20261023_0114 was applied to the configured shared production database. Deploy this backend revision to start the background workers. Optional DATABASE_POOL_SIZE and DATABASE_MAX_OVERFLOW settings now control the application pool; defaults remain 10 and 10.
