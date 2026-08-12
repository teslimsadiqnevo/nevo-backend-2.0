# SCRUM-62: Gaming detection architecture

Architecture and schema only. Implementation is post-launch.

## Scope

Pattern recognition for intentional signal manipulation: a student slowing
responses or generating errors on purpose to pull easier content. Ranked low
risk (#4); the schema lands now so the engine does not need a retrofit.

## Acceptance criteria

1. Learner profile schema carries a stored-only gaming suspicion flag
   (`learner_profiles.gaming_suspicion_level`), defaulting to `none` and
   surfaced to nobody.
2. Pattern anomalies are recordable against a learner's own baseline via
   `learner_engagement_anomalies`, including the deviation ratio, the breadth
   across content types, and the rule that fired.
3. Threshold rules are documented and expressed as data in
   `nevo.domain.learner_profiles.gaming_rules`, keyed so stored rows stay
   attributable after a threshold revision.
4. Teacher notification copy is defined with positive framing and carries no
   accusation.
5. No runtime detection logic. Nothing reads or writes the new columns.

## Threshold rules

Every rule requires breadth: `ALL_CONTENT_TYPES` scope plus a minimum spread
of distinct content types. Deviation is always against the learner's own prior
baseline, never a cohort average.

| Rule key | Ratio | Min observations | Min content types | Sessions | Level |
| --- | --- | --- | --- | --- | --- |
| `response_time_doubled_everywhere` | 2.0x | 8 | 3 | 2 | moderate |
| `response_time_tripled_everywhere` | 3.0x | 8 | 3 | 3 | high |
| `errors_spike_against_mastery` | 2.5x | 10 | 3 | 2 | low |
| `abandoned_attempts_spike` | 2.0x | 6 | 3 | 2 | low |

Error and abandonment rules cap at `low` alone: disengagement and frustration
produce the same shape, so neither reaches a teacher without a corroborating
sustained uniform slowdown.

## Teacher notification copy

Positive framing, proposing a change to the material rather than reporting the
learner. Nothing is shown to the student at any level, and `none` has no copy.

- **low**: "{student_name}'s recent work looks different from their usual
  pattern. Worth a look when you have a moment."
- **moderate**: "{student_name} may be finding this content too easy. Consider
  assigning more challenging material."
- **high**: "{student_name} may be ready to move on from this material.
  Consider stepping the difficulty up, or having a quick chat about how they
  are finding it."

## Definition of done

- [x] Schema updated with gaming detection fields.
- [x] Rules documented ([ADR 0008](../adr/0008-gaming-detection-architecture.md)).
- [x] No runtime logic implemented.

## Notes

Ratios are reasoned starting points, not measured against production traffic.
Tune before anything surfaces to a teacher.

The stored column name reads as accusatory if it ever reaches an export or a
subject access response. Nothing surfaces it today and it is kept out of the
dimension mixin, but the name is worth revisiting before the engine ships.
