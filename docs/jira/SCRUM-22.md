# SCRUM-22: Signal events table

## Scope

Build the high-volume `signal_events` storage contract for adaptive learner
engagement and pacing signals.

## Acceptance criteria

1. `signal_events` stores `student_id`, `session_id`, `event_type`,
   `event_data`, and `timestamp`.
2. `event_type` is constrained to the ticket-defined signal vocabulary.
3. `event_data` is PostgreSQL `JSONB` for event-specific payloads.
4. `student_id` references canonical `users.id`; `session_id` remains a UUID
   correlation identifier until a learning-session table exists.
5. The table has indexes on `(student_id, session_id)`,
   `(student_id, timestamp)`, and `(event_type, timestamp)`.
6. Rows are append-only at the database level.
7. The schema is compatible with future monthly partitioning when volume
   requires it.

## Implementation note

The initial table is unpartitioned to keep migrations simple while the product
is pre-scale. Partitioning can be introduced later with a planned data migration
once retention and volume thresholds are known.
