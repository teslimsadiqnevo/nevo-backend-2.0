# Remaining Adaptation Backend Fixes

Date: 18 October 2026

This follow-up addresses the two 17 October engineering notes, not just the original backend checklist. It supersedes any earlier wording suggesting those notes were fully closed.

## Backend Changes

1. Removed the four channel-preference dimensions and the legacy processing-channel preference from both current profile and profile-history models. Migration `20261018_0104` removes their stored columns, related preference flags and structured historical evidence keys. Inference, Ask Nevo context and new progress-export evidence no longer use these classifications. Generic account settings reject attempts to reintroduce them with `422 learning_style_not_stored`.
2. Segment opening order and modality come from authored lesson content, not a preference assigned to the child. Switching still requires current-session evidence, available content and rate limits.
3. The adaptation API derives comprehension, personal references, response-time changes, engagement, errors, replay counts and uninterrupted duration from saved marked attempts and permitted stored events. Client-supplied computed scores cannot manufacture an adaptation; a pause alone is not interpreted as a comprehension failure.
4. `acceptedAnswers` survives checkpoint and calculation-step delivery. Marking supports explicit accepted alternatives and bounded numeric equivalence, including `0.5`, `1/2`, `2/4` and `50%`, without evaluating executable input. Choice IDs are not silently treated as interchangeable numbers.
5. Answer persistence already updates mastery transactionally; lesson completion now also creates the first concept review schedule even before the student has reached the mastery threshold. Repeating completion does not duplicate schedules or reset an existing review history.
6. A short baseline recalibration preserves unmeasured dimensions, subject placement and unrelated delivery settings. It does not replace the whole baseline with default values.
7. Timed reading trials can send `readingWordCount` alongside `responseTimeMs`; WPM is calculated server-side. Missing reading measurements are not persisted as a measured 120 WPM. A delivery default is not evidence about the child.
8. Daily warm-up rotation is exactly `wmc`, `ps`, `reading`, `ans`, `attention`, `domain`. Motor calibration remains accepted as a device capability measurement but is not a seventh warm-up day.
9. Child-facing check-in copy no longer says every answer was right. Progress prose is based on recorded learning activity, not a mastery band.
10. Accommodation analysis understands the current permitted event vocabulary and recorded answer timing, not only older fields that clients do not send. The five-distinct-lesson, multi-signal confirmation rule and session-frozen delivery still apply.
11. The depth backfill handles null and partially populated variants, fills only missing bodies, bounds generation concurrency and splits oversized sources. Dry-run is read-only and makes no model calls. It never regenerates lesson segments or resets saved places or original approval identities.
12. Source key terms and equation callouts accompany depth delivery. Pending backfill variants are withheld from student reads, offline packages and adaptation availability until the existing segment-approval action approves them. Existing approved source material remains available.

## Frontend Integration Notes

- Continue sending observed events and answers. Do not calculate engagement/comprehension scores on the device; the adaptation endpoint no longer trusts those supplied scores.
- Send observed answer `responseTimeMs` and `hintCount`. For a timed reading trial, send the number of words actually displayed as `readingWordCount`; do not infer a WPM value on the client.
- Use `acceptedAnswers` where answer options or local display require it, but persisted correctness is the server's verdict.
- Retain key-term and equation boxes during Simplify/Expand; depth payloads carry their source annotations. Their visual preservation still requires frontend verification.
- Existing approval routes approve pending depth variants without changing the original approval identity. Teachers can read the variants while students cannot access pending rewrites.
- Use `/api/v1/students/me/onboarding`, the authenticated subject probe, and next-work reads from the preceding handoff. Probe banks and real curriculum prerequisites are school content/configuration, not fabricated fallback data.

## Deliberate Boundaries

No frontend files were changed. Site routing and CI API URLs, the calculation player's final-tap behaviour, consent-screen Back navigation, rendered annotation boxes and visible support changes still require frontend acceptance. The old Render service's suspension reason cannot be established from this codebase. Product decisions about retired screens/pills are not silently reversed by this patch.

The backend does not manufacture a simplified rewrite when fidelity checks reject a model output. Backfill completion counts, rejected content, migration results and deployment verification belong in the final release report, rather than being assumed from a successful script exit.
