# Backend implementation checkpoint - 2026-08-30

## Completed in the current uncommitted batch

- Replaced baseline feature-count storage with deterministic baseline profile and engine configuration generation.
- Replaced static school analytics and empty outcome responses with database aggregates.
- Made the legacy settings compatibility routes persist and return `User.preferences`.
- Added tenant and assignment checks to mastery, scheduler, IEP export, Ask Nevo helpfulness, and generic AI routes.
- Added a mandatory outbound AI privacy guard that strips or pseudonymises direct identifiers before any provider call.
- Added engine configuration, student adaptations, conversation evidence, class misconceptions, transformation metrics, and student progress APIs.
- Added real invoice PDF generation, lesson offline ZIP generation, upload structure undo, and notification restore.
- Added Resend-backed password reset and invitation delivery with explicit unavailable states when email infrastructure is not configured.
- Added an admin/SENCo student PIN reset endpoint that revokes active sessions and returns a one-time replacement PIN.

## Completed after the frontend contract request

- Added real Microsoft 365 and Google Workspace roster clients, class mapping,
  tenant validation, encrypted refresh-token storage, and Drive/OneDrive imports.
- Added durable post-lesson and notification-email workers with retry state.
- Restricted messaging to authorised participants and made unread state durable.
- Added migration `0030` for the new operational state and product contracts.
- Finalised Claude-only and provider deployment environment documentation.
- Unified lesson modules and segment review information in one response.
- Added teacher Home pulse/activity, student observations, and per-segment class
  completion APIs.
- Typed staged-upload structure editing, retained upload bytes for page retry,
  and added selected-page PDF re-parsing.
- Removed engine parameters from teacher-facing profile reads and made Ask Nevo
  evidence aggregate-only with a minimum group of three interactions.
- Added lesson subject, assignment count, assignment availability, message class
  and unread state, mastery concept names, progress ordinals, and flag evidence
  and action targets.
- Added application request timing headers and slow-request logging.

## Current frontend contract priority

The product routes use typed camel-case contracts. Original authentication
responses retain snake case as an explicit compatibility contract.

Microsoft/Google sign-in, directory sync, Drive imports, and email delivery need
real provider credentials in the deployment environment. The backend reports
explicit unavailable or needs-attention states until those credentials exist.
