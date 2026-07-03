# ADR 0001: Zero-Tag learner profile schema

- Status: Accepted for SCRUM-15
- Date: 2026-07-02
- Owners: Nevo backend team

## Context

Nevo adapts learning experiences from functional observations. The platform must
not infer, store, expose, or transmit clinical or diagnostic labels. A learner
profile therefore describes how a learner currently interacts with learning
content, not why that behavior occurs.

## Decision

The canonical profile has six functional dimensions:

1. `processing_channel_preference`
2. `cognitive_load_threshold`
3. `processing_speed`
4. `working_memory_capacity`
5. `attention_span`
6. `performance_sensitivity`

Every dimension has a separate confidence value using the shared
`profile_confidence` enum: `low`, `medium`, or `high`.

`processing_channel_preference` uses a controlled functional vocabulary:
`visual`, `auditory`, `textual`, `interactive`, `multimodal`, or `undetermined`.
The remaining dimensions are observations, not identities:

- `cognitive_load_threshold`: 1-5 functional scale
- `processing_speed`: 1-5 functional scale
- `working_memory_capacity`: 1-5 functional scale
- `attention_span`: observed sustainable minutes, 1-240
- `performance_sensitivity`: 1-5 functional scale

The scales deliberately describe product behavior. They are not medical scores
and must not be presented as diagnoses.

`learner_profiles` stores the current state. `learner_profile_history` stores
immutable, versioned snapshots. History records include change source, optional
actor, reason, and timestamp.

The profile references a learner with `learner_id`. Its foreign key is deferred
until SCRUM-16 creates the canonical `users` table. The unique learner constraint
prevents duplicate current profiles in the interim.

## Enforcement

- PostgreSQL enums and checks constrain all values.
- History rows cannot be updated or deleted.
- Schema contract tests scan table names, columns, constraints, indexes, and enum
  values for prohibited diagnostic terminology.
- Application services must append history and update the current profile in one
  transaction.

## Consequences

- Functional observations remain queryable and strongly typed.
- Profile evolution is auditable without overwriting earlier states.
- Adding a new dimension requires a migration and an explicit architecture review.
- A later migration must add the `learner_id -> users.id` foreign key after
  SCRUM-16 lands.
