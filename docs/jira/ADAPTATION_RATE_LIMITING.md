# Adaptation Rate Limiting

Implemented the cooldown layer for in-lesson adaptation decisions.

## Rules

- Minimum segment dwell before a modality shift can fire: 90 seconds.
- Cooldown after any adaptation before another can fire: 120 seconds.
- Maximum modality shifts per lesson session: 3.

These limits are applied after the adaptation engine identifies a candidate change, so suppressed attempts can be logged for later analysis.

## API Contract

`POST /api/intelligence/adapt` accepts optional session/timing fields:

- `sessionId`
- `signals.currentSegmentElapsedSeconds`
- `signals.secondsSinceLastAdaptation`
- `signals.sessionModalityShiftCount`

When `sessionId` is present, the backend also reads prior signal history for that lesson session.

## Suppression Logging

Suppressed attempts are appended to `signal_events` as:

- `event_type`: `adaptation_suppressed`
- `event_data`:
  - `lessonId`
  - `attemptedType`
  - `reason`
  - `segmentId`
  - `currentModality`
  - `suggestedModality`

The `reason` is one of:

- `minimum_dwell_time`
- `adaptation_cooldown`
- `session_modality_shift_cap`
