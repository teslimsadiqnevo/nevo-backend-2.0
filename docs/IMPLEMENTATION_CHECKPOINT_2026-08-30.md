# Backend implementation checkpoint - 2026-08-30

## Completed in the current uncommitted batch

- Replaced baseline feature-count storage with deterministic baseline profile and engine configuration generation.
- Replaced static school analytics and empty outcome responses with database aggregates.
- Made the legacy settings compatibility routes persist and return `User.preferences`.
- Added tenant and assignment checks to mastery, scheduler, IEP export, Ask Nevo helpfulness, and generic AI routes.
- Added a mandatory outbound AI privacy guard that strips or pseudonymises direct identifiers before any provider call.
- Added engine configuration, student adaptations, conversation evidence, class misconceptions, transformation metrics, and student progress APIs.
- Added real invoice PDF generation, lesson offline ZIP generation, upload structure undo, and notification restore.
- Added SMTP-backed password reset and invitation delivery with explicit unavailable states when email infrastructure is not configured.
- Added an admin/SENCo student PIN reset endpoint that revokes active sessions and returns a one-time replacement PIN.

## Work paused for the frontend contract request

- Implement real Microsoft 365 and Google Workspace roster retrieval, then map provider classes into student enrolments and teacher class assignments.
- Add tenant validation to the school-slug roster-sync compatibility route.
- Add durable post-lesson processing status, retries, and background worker.
- Finish any remaining authorization audit items, especially messaging participant rules.
- Add migration `0030` for any new persistent retry/SSO fields required by the completed implementation.
- Finalise Claude-only deployment environment documentation and remove obsolete Gemini deployment examples.
- Run PostgreSQL migrations, integration tests, the full test suite, then commit and push.

## Current frontend contract priority

The active task is to type every JSON response in OpenAPI, document the eleven shapes that could not be inferred from empty demo data, declare canonical casing, correct the acceptance checklist category wording, verify the extra routes, and push those changes.
