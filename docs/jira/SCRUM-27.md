# SCRUM-27: Break threshold monitoring

## Scope

Build rule-based break threshold monitoring and break type selection for
real-time lesson support.

## Acceptance criteria

1. Detect 20 minutes of continuous work.
2. Detect engagement decline for three minutes below personal baseline.
3. Detect comprehension drops of at least twenty points below session average.
4. Detect three or more consecutive errors.
5. Detect three or more replays on the same segment.
6. Select `micro`, `movement`, `consolidation`, or `full` breaks based on the
   fired thresholds and learner profile.
7. Avoid Gemini calls for break decisions so the response is fast enough for
   in-lesson use.

## Notes

The break monitor is used by `/api/intelligence/adapt` and is independently
tested so future endpoints can reuse it directly.
