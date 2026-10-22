# Sitting-wide depth and pacing

## Contract

The existing PUT
`/api/v1/lessons/{lessonId}/sessions/{sessionId}/segments/{segmentId}/preferences`
still accepts `depth`, `slower` and `modality`.

- `depth` and `slower` now apply throughout the current sitting, not just that segment.
- `modality` remains specific to the selected segment.
- Partial writes preserve the other settings; `slower: false` and `depth: original`
  explicitly turn the respective choice back off.
- A new sitting starts without inherited choices. An ended/completed sitting's public
  delivery state does not expose its old choices as active review settings.
- No local-storage state or per-section write is required to carry depth forward.
- The latest choices in old active sittings are interpreted at sitting scope on read;
  the next preference write saves that normalized state. No database migration is required.

Session `deliveryState` and preference-write responses expose typed `lessonPreferences`
with `depth`, `slower` and `updatedAt`. Segment `deliveryPreference` and adapt responses
continue exposing the effective settings for that section, including inherited settings.
`segmentChoices` retains section-specific format choices.

The target depth remains saved when a section lacks an approved matching rewrite,
but that section's effective depth is `original`. An unapproved rewrite is never served;
the selected depth resumes on a later section that has an approved version.

Also corrected an existing invalid import in the depth preference write, which otherwise
raised ImportError when selecting Simplify or Expand.

## Verified production facts on 22 October

- Osmosis 3367de9d's narration slots 1, 3, 4 and 5 are already populated following the
  successful rotated-key repair. All four Storage objects were checked and exist.
  No unnecessary generation/rebilling should be triggered.
- Current public health reports schema 0112, image provider configured, but its last-call
  outcome is unknown and last-failure is empty. Configured is not proof of a real success.
- The latest retained parse-note image failure found is from 16 October at 15:05 UTC:
  HTTP 429, `credit_balance_exhausted`, message "You have no credits remaining."
  It is historical evidence, not a diagnosis of today's reported $10.21 balance.
- This checkout has no OpenAI key. The key's project and its billing restrictions cannot
  be inferred from that old error or the public health response. The Render key's owning
  OpenAI project/organisation must be checked by the account holder.

## Unresolved and explicitly deferred

- Admin E2E: no failing URL, response status, incident or trace supplied. Await the named
  failing page and trace if the rerun still fails; do not assign a speculative backend cause.
- Break expiry needs no change: Yinka clarified the item meant the confusion grace window.
- After demo: parser-authored primary format needs its own implementation and validation.
- After demo: boredom should select a harder item in the same concept, not reduce support.
  Neither deferred change is represented as shipped by this patch.
