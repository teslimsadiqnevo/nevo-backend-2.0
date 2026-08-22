# Non-invasive affective inference engine

## Scope

This ticket is implemented as a client-side browser module in
`frontend/affective/affective_inference.js`. The backend intentionally does not
receive, persist, or infer from affective behavioural signals.

## Privacy boundary

1. Raw behavioural signals stay in browser IndexedDB for the active lesson
   session only.
2. `cleanupAffectiveSession()` deletes the IndexedDB database at session end.
3. The inferred affective state is never stored as a backend learner profile
   dimension, attention flag, or diagnostic label.
4. The module contains no network transport calls for affective data.
5. Affective baselines are scoped by form factor: `tablet_touch`,
   `desktop_cursor`, or `mobile_touch`.

## Supported states

- `neutral`
- `anxiety`
- `boredom`
- `frustration`
- `confusion`

## Supported local signals

Tablet and mobile touch signals are first-class:

- `tap_latency`
- `tap_duration`
- `aborted_gesture`
- `inter_touch_idle`
- `scroll_pattern`
- `gesture_completion_rate`

`cursor_dwell_time` is deliberately retired. Touch dwell is represented by
`tap_duration`; gaps between touches are represented by `inter_touch_idle`.

## System busy exclusion

The module accepts local system-busy markers through `recordSystemBusyMarker`.
Signals that occur inside a busy interval are ignored during inference so app
loading, audio buffering, scaffold generation, and similar UI work do not become
false idle or hesitation evidence.

## Threshold rules

Anxiety requires at least three signal categories sustained for thirty seconds:
uneven typing or tap rhythm, elevated deletion or aborted gesture, rapid scroll,
and elevated error rate.

Boredom requires at least two signal categories sustained for sixty seconds:
slow scroll, idle of ten seconds or more, and off-content scrolling.

Frustration requires at least two signal categories sustained for twenty
seconds: repeated clicks or taps, sudden acceleration, and rapid backspace or
backscroll.

Confusion requires at least two signal categories sustained for thirty seconds:
question/reference transitions, hesitation or idle, and hovering or
noninteractive taps.

## Productive confusion

Confusion starts with a grace window instead of an immediate intervention. The
base grace window is forty-five seconds for Primary, sixty seconds for JSS, and
ninety seconds for SS. The window is scaled by
`base_grace_sec * (0.5 + 0.5 * normalized_attention_d_prime)`.

Confusion is treated as productive when the learner remains engaged through
attempts, rereading, or reference checking. It becomes intervention-ready only
after the grace window when the learner is stalled for more than fifteen
seconds, has three or more consecutive errors on the same step, or skips/exits.

## Baseline integration

The engine accepts `motor_baseline_ms`, `tau_ps`, and `attention_d_prime` as
optional calibration inputs. Slow motor timing alone is not enough to classify a
learner as bored or confused, which protects accurate slow processing from being
misread as disengagement.

## Public browser functions

- `recordAffectiveSignal(signal)`
- `recordSystemBusyMarker(marker)`
- `getCurrentAffectiveState(options)`
- `shouldTriggerAffectiveAdaptation(state, options)`
- `cleanupAffectiveSession()`
- `attachAffectiveCaptureListeners(root, options)`

The pure helpers `inferAffectiveStateFromWindow`,
`evaluateAffectiveWindow`, `evaluateProductiveConfusion`, and
`calibratedConfusionGraceMs` are exported for deterministic tests and frontend
state management.

