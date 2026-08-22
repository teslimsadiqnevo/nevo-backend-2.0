# Hybrid AKT mastery engine with Decoupled Dual-Skill Modeling

Implemented the v1 mastery layer that dashboard progress views can read.

## Backend Contract

- `POST /api/mastery/update`
- `GET /api/mastery/student/{student_id}`
- `GET /api/mastery/class/{class_id}`
- `GET /api/mastery/school/{school_id}`

## Schema

`student_concept_mastery` stores one row per student and concept:

- `mastery_probability_concept`
- `mastery_probability_reading`
- `attention_weights`
- `guess_probability`
- `slip_probability`
- `practice_count`
- `last_response_correct`
- `last_failure_attribution`

Rows are unique by `(student_id, concept_id)` and indexed by student, concept,
and the combined read path.

## Algorithm

The v1 engine is a pragmatic Hybrid AKT implementation:

- concept and reading mastery are separate latent states
- related concepts contribute through attention weights
- correct responses increase mastery through an exponential learning curve
- incorrect text-heavy responses with low reading probability are attributed
  to reading, not concept mastery
- visual or interactive failures with adequate reading probability update
  concept mastery downward
- borderline cases use mixed attribution based on text density

## SCRUM-104 Dependency

SCRUM-104 baseline profiling is not present in this backend yet. The mastery
repository has a seeding contract for `theta_domain`, `reading_wpm`, and
`age_band`, but currently falls back to conservative defaults:

- concept seed: `0.15`
- reading seed: `0.5`
- concept seed cap from baseline: `0.7`

When SCRUM-104 lands, the repository can read those baseline fields without
changing the API or mastery table.

## Out of Scope

Deferred exactly as ticketed:

- transformer DKT
- signed Q-matrix misconception detection
- production parameter tuning
- generative Socratic hinting
