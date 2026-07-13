# SCRUM-23: Batched signal ingestion API

## Scope

Build the high-throughput `POST /api/signals/` endpoint for frontend batched
signal submission and add `lesson_sessions` tracking for resume and completion
state.

## Acceptance criteria

1. The ingestion endpoint accepts batched signal events.
2. Events use the authenticated student as the authoritative `student_id`.
3. `lesson_sessions.id` is the frontend `sessionId`, allowing cheap joins from
   `signal_events.session_id`.
4. `lesson_sessions` stores `student_id`, `lesson_id`, `started_at`, `ended_at`,
   `completion_status`, `exit_position`, `break_count`, and
   `proactive_adjustments_count`.
5. The six modality-switching signal event types are supported:
   `modality_suggestion_shown`, `modality_suggestion_accepted`,
   `modality_suggestion_declined`, `modality_suggestion_ignored`,
   `modality_switch_outcome`, and `modality_manual_switch`.
6. Top-level event fields from the frontend are persisted into `event_data` for
   event-specific payloads.
7. Writes are batched through one repository transaction using bulk insert.

## Notes

The frontend flush cadence remains client-owned: every five seconds, at twenty
events, or on lesson exit/completion. The backend accepts up to 100 events per
request so retry coalescing does not reject otherwise valid payloads.
