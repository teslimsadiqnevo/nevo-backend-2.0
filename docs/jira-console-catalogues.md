# SCRUM-131 and SCRUM-245

All four reads require a signed-in teacher or school administrator. No frontend files were changed.

## Library totals

`GET /api/content/lessons/totals?scope=mine|school` returns `lessonsUploaded`, `liveToClasses`, and `inReview` across the complete accessible library. Scope has the same default and access rules as the lesson list. Counts do not depend on pagination.

`liveToClasses` counts distinct lessons with a non-cancelled class assignment whose availability has begun. `inReview` counts distinct lessons with an unapproved flagged segment or an unresolved unsure key point. Multiple students, assignments, segments, or key points never multiply a lesson's count. The counts may overlap.

## Upload reason codes

`GET /api/v1/uploads/reason-codes` returns the closed `codes` list and `fallbackCode: "unknown"`.

Codes: `file_too_large`, `unsupported_file_type`, `unreadable_file`, `no_readable_text`, `preparation_timeout`, `service_busy`, `save_failed`, `output_limit`, `partial_reading`, `unknown`.

`POST /api/v1/uploads/batch` includes nullable `reasonCode` per file. Rejected files receive a code; accepted files have null. Upload list/detail reads also carry `reasonCode`: failed parses receive a failure code, reads with failed pages receive `partial_reading`, and successful complete reads have null. Existing `error`, `failureReason`, and `incidentId` fields remain available. Use the code for mapped display copy; use the fallback for unrecognised future codes.

## Help categories

`GET /api/intelligence/help-categories` returns `codes` and `fallbackCode: "general"`. The closed list is `lesson_help`, `profile_pattern`, `class_planning`, `family_message`, `flag_review`, `general`. This is the category vocabulary used by the help-seeking map, not the separate student/teacher question signal categories.

## Pulse thresholds

`GET /api/intelligence/pulse-thresholds` returns the score range (0 to 100), band codes, inclusive lower bounds, upper bounds, upper-bound inclusion, display labels, and the no-data label. It uses the same definitions as Teacher Home's pulse labels:

- `support`: 0 <= score < 50; `May benefit from support`.
- `mixed`: 50 <= score < 75; `Mixed`.
- `steady`: 75 <= score <= 100; `Steady`.
- Missing data: `Still gathering a picture`.

The current backend owns this display policy. These bands describe aggregated class pulse scores; they are not diagnostic thresholds or a claim of research validation. Teacher Home already returns the chosen words, so the frontend can render them without applying cutoffs itself.

No migration is required.
