# Frontend Handoff Backend Contract

## Section 04: Ephemeral interaction signals

The frontend captures high-resolution interaction timing locally for the active
lesson session. These events are ephemeral browser inputs for client-side
inference and must not be sent to backend APIs.

### Dwell timing field

Use `interaction_dwell_time` for form-factor-neutral dwell measurement.

Capture semantics:

- Cursor form factors: time between the cursor entering an element and either
  clicking it or leaving it.
- Touch form factors: time between tap-down and tap-up, or the interval between
  the first tap on an element and the next interaction.

Do not fabricate cursor dwell data on tablet or mobile flows. Touch interaction
timing must stay touch-native.

### Raw touch signal exclusion

The following raw touch signals are IndexedDB-only, ephemeral, and deleted at
session end:

- `tap_latency`
- `tap_duration`
- `aborted_gesture`
- `inter_touch_idle`
- `scroll_pattern`
- `gesture_completion_rate`

The backend, ops schema, ops event feed, ops adaptation log, teacher console,
admin dashboard, exports, and downstream APIs must not receive these raw
signals. Only derived session behaviour may influence the learner experience,
and the derived affective state is never persisted or rendered as a visible
label.
