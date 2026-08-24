# SCRUM-70: Affective inference compliance guard

## v1 guard

Raw touch signals never surface outside the client affective inference module.
The browser may use these signals locally during the active lesson session:

- `tap_latency`
- `tap_duration`
- `aborted_gesture`
- `inter_touch_idle`
- `scroll_pattern`
- `gesture_completion_rate`

They are IndexedDB-only, ephemeral, and deleted at session end. They are not
sent to the backend, stored in learner profile tables, written into signal event
rows, logged in ops, exported, or passed to any downstream API.

The affective inference engine may produce a derived session state such as
neutral, anxiety, boredom, frustration, or confusion. That derived state may
shape design behaviour during the active session, but it is never persisted and
never rendered as a visible label. Teacher, admin, and ops surfaces must use
functional wording only and must not reveal either raw touch events or affective
state labels.

## Handoff correction

Build against `interaction_dwell_time`, not the retired cursor-specific field.
Cursor form factors measure element enter-to-click or enter-to-leave timing.
Touch form factors measure tap-down to tap-up duration, or the interval between
the first tap on an element and the next interaction. Tablet flows must not
fabricate cursor dwell data.

## DPIA note

This guard should be added to the DPIA before v1 launch because it proves raw
touch interaction streams remain local, temporary, and non-operational.
