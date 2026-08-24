# SCRUM-53: Signal collection compliance guard

## v1 guard

Raw touch signals never surface outside the browser collection layer. The
following events are IndexedDB-only, ephemeral, and deleted at session end:

- `tap_latency`
- `tap_duration`
- `aborted_gesture`
- `inter_touch_idle`
- `scroll_pattern`
- `gesture_completion_rate`

The `/api/signals/` ingestion path must not accept these raw touch events. They
must not appear in the ops schema, ops event feed, ops adaptation log, teacher
console, admin dashboard, exports, product intelligence feeds, or any downstream
API. Only aggregated lesson signals and Ask Nevo usage signals belong in the
backend event pipeline.

Only derived affective state may influence session behaviour. That state is
session-scoped, never persisted, and never rendered as a visible label. If a
plain-language event is shown in an ops or school-facing surface, it must be
generated at the moment of surfacing from derived state and current context, not
from raw touch signal storage.

## Handoff correction

The frontend handoff contract uses `interaction_dwell_time` for ephemeral dwell
measurement. The old cursor-specific wording is retired. On cursor form factors
it means time between entering an element and clicking or leaving. On touch form
factors it means tap-down to tap-up duration, or the interval between the first
tap on an element and the next interaction.

## DPIA note

This rule is NDPA-relevant. Counsel should reference this guard in the v1 DPIA:
raw touch interaction streams are local, temporary, and excluded from operational
data stores.
