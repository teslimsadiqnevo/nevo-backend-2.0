# Progressive scaffold fading

## Scope

The co-construction calculation mechanic now tracks concept-level scaffold state
per student and logs the support level shown on each problem.

## Scaffold levels

1. `full_support`
2. `partial_support`
3. `hints_only`
4. `independent`

## Fading rule

After three consecutive successful problems at a scaffold level, the next
problem moves one step toward independence. For example, three successful
problems at `full_support` set problem four to `partial_support`.

Successful mastery signals include:

- correct step or problem response
- response time not far above expected time
- stable or reduced reliance on hints

## Re-engaging support

When a student struggles after a scaffold reduction, the next problem moves one
step back toward support. Student-facing copy is neutral and does not describe
the event as failure.

## API

- `GET /api/intelligence/scaffolds/state/{student_id}/{concept_id}`
- `POST /api/intelligence/scaffolds/attempt`
- `GET /api/intelligence/scaffolds/history/{student_id}`

The history endpoint supports teacher and SENCo dashboard visibility.

## Persistence

`student_concept_scaffold_states` stores operational state for the next problem.
`scaffold_problem_logs` stores per-problem support level history for staff
visibility.
