# ADR 0008: Gaming detection architecture

## Status

Accepted. Schema and thresholds only (SCRUM-62). No runtime logic.

## Context

Research flagged that a student may try to steer Nevo toward easier content by
intentionally slowing responses or producing errors. It was ranked low risk
(#4), so building detection now would be premature. Adding the schema later
would mean migrating a large, hot table and backfilling profile state, so the
foundation goes in now and the engine follows post-launch.

The hard part is not measuring a slowdown. It is separating a student steering
the system from a student who is genuinely tired, bored, or struggling. Those
produce a similar signal, and the cost of getting it wrong is a child wrongly
treated as dishonest.

## Decision

### Breadth is the discriminator

Genuine difficulty concentrates in a content type. A learner who finds worked
examples hard slows down on worked examples. Intentional manipulation spreads
evenly, because the student does not know which content type drives the
adaptation. Every rule in `nevo.domain.learner_profiles.gaming_rules`
therefore requires `ALL_CONTENT_TYPES` scope and a minimum spread of distinct
content types. A doubling within one content type is a teaching signal, not a
gaming signal, and is left to the existing adaptation path.

### Baselines are per learner

Deviation is always measured against the learner's own prior norm, never a
cohort average. A cohort baseline would flag slower learners as suspicious by
construction, which is exactly the failure this design exists to avoid.

### Evidence and judgement are separate

`learner_engagement_anomalies` is an append-only ledger of observations. Each
row carries the `rule_key` that produced it, so thresholds can be revised
without orphaning history. The summarised judgement lives on
`learner_profiles.gaming_suspicion_level`, which starts at `none` and has a
database check tying a non-`none` level to a timestamp.

`gaming_suspicion_level` is deliberately **not** on
`LearnerProfileDimensionsMixin`. It is not a learning dimension, must not
enter the inference dimension set, and must not appear in a progress export.

### Thresholds

Defined as frozen data in `gaming_rules.py`, not as code. The module has no
function that inspects a learner. Summary:

| Rule | Ratio | Sessions | Level |
| --- | --- | --- | --- |
| `response_time_doubled_everywhere` | 2.0x | 2 | moderate |
| `response_time_tripled_everywhere` | 3.0x | 3 | high |
| `errors_spike_against_mastery` | 2.5x | 2 | low |
| `abandoned_attempts_spike` | 2.0x | 2 | low |

Each rule also sets a minimum observation count and a minimum spread of
distinct content types, so one bad afternoon cannot trip it.

Error and abandonment rules cap at `low` on their own. Both shapes are
produced just as readily by disengagement or frustration, so neither should
reach a teacher without a corroborating sustained, uniform slowdown.

### What a teacher sees

Never the stored level, and never an accusation. The notification proposes a
change to the material:

> Kofi may be finding this content too easy. Consider assigning more
> challenging material.

This is the useful action whether or not the underlying guess is right. If the
student was steering the system, harder material addresses the boredom driving
it. If the read was wrong, the teacher has been prompted to look at a student
whose pattern changed. Neither path requires the student to be told they were
suspected, and no path shows the student anything.

## Consequences

The detection engine can be built without a migration against a large table.
Thresholds are reviewable by non-engineers in one file and revisable without
touching stored history.

The stored column name reads as accusatory if it ever escapes into an export
or a subject access response. Nothing surfaces it today, and the separation
from the dimensions mixin keeps it out of the progress export path, but any
future contract that serialises a learner profile wholesale must exclude it
explicitly. Worth revisiting the name before the engine ships.

The rules are unvalidated against real data. The ratios are reasoned starting
points, not measured ones, and should be tuned against production traffic
before anything is surfaced to a teacher.
