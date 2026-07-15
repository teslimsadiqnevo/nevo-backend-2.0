# SCRUM-25: Post-lesson profile update cycle

## Scope

Build the post-lesson learner profile update cycle that summarizes a completed
lesson session, sends the evidence and current profile through the AI Gateway,
and writes a trend-tracking history snapshot when the recommendation is safe to
apply.

## Acceptance criteria

1. Session signal data is aggregated from `lesson_sessions` and `signal_events`.
2. The update request is sent through the existing Gemini-backed AI Gateway with
   the current learner profile and session summary.
3. Gateway responses are parsed as strict JSON recommendations for canonical
   profile dimensions and confidence levels.
4. Normal recommendations update `learner_profiles` and insert a
   `learner_profile_history` snapshot with `system_inference` as the source.
5. Significant divergence from a high-confidence existing profile creates a
   `learner_profile_attention_flags` record for educator review instead of
   auto-updating the profile.
6. The seeded `profile_update.default` prompt uses escaped JSON braces so it is
   safe for the prompt renderer.

## Notes

Sudden-change detection is conservative: it only blocks auto-update when the
existing dimension is high confidence and the recommended value jumps by at
least two strength/scale points, or by at least sixty minutes for
`attention_span`.
