# SCRUM-30 IEP Export Workflow

Implemented the export service for board-ready progress document drafts.

## Backend Contract

- Added `iep_exports` with draft/final status.
- Added `iep_export_shares` for parent/guardian account sharing.
- Added `student_record_events` for audit logging.
- Added `POST /api/v1/exports/iep` to generate a draft.
- Added `GET /api/v1/exports/iep/{export_id}`.
- Added `PATCH /api/v1/exports/iep/{export_id}` for draft edits and annotations.
- Added `POST /api/v1/exports/iep/{export_id}/review` for mandatory SENCo finalization.
- Added `POST /api/v1/exports/iep/{export_id}/share` for parent account sharing after finalization.

## Evidence Aggregation

Draft generation aggregates the selected reporting period:

- learner profile dimension history
- signal trend counts
- attention flags
- escalations
- intervention recommendations

## SENCo Review Gate

Exports are created as drafts and cannot become final without:

- `reviewed_by_user_id`
- `reviewed_at`
- caller role `senco_admin`

Sharing is blocked until the export is final.

## Zero-Tag Generation

The Gemini prompt seed `iep_export.draft` instructs board-ready functional language only. The service also runs the generated content through the existing Zero-Tag compliance policy before saving the draft.
