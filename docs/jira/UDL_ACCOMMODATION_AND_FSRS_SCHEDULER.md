# UDL accommodation inference and FSRS scheduler

## UDL dynamic accommodation inference

The accommodation layer is calculated on demand from aggregated behavioural
patterns in prior lesson sessions. It does not write a persistent student
accommodation label.

The backend endpoint is:

- `GET /api/intelligence/accommodations/{student_id}`

The response includes:

- active accommodations: `reading`, `attention`, `numerical`
- frontend signals: `reading_accommodation_active`,
  `attention_accommodation_active`, `numerical_accommodation_active`
- evidence keys used for the decision
- `persistedAsLabel: false`

Each accommodation requires at least three aligned evidence categories across
five completed lessons. Numerical accommodation also requires five maths
lessons.

The frontend helper in `frontend/udl/accommodations.js` exposes:

- `applyAccommodationSignal(payload)`
- `getActiveAccommodations()`
- `clearActiveAccommodations()`

It stores only current-session state in memory.

## FSRS spaced repetition scheduler

The scheduler persists concept review timing in
`student_concept_scheduling`. It tracks:

- `student_id`
- `concept_id`
- `stability`
- `difficulty`
- `last_review`
- `review_count`
- `next_review_due`

Retrievability is calculated at read time:

`R(t, S) = (1 + alpha * t / S)^(-beta)`

Initial constants are `alpha = 1.0`, `beta = 1.0`, and the review threshold is
`0.85`.

The backend endpoints are:

- `GET /api/scheduler/due-reviews/{student_id}`
- `POST /api/scheduler/record-review`
- `POST /api/scheduler/refresh-due-dates`

`record-review` creates the first schedule for a concept or updates an existing
schedule after successful or unsuccessful recall. A successful first review is
scheduled roughly one to three days later with the current launch constants.
