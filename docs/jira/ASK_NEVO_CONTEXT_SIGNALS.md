# Ask Nevo context signals

## Scope

Ask Nevo product-intelligence events are now supported in `signal_events`.
These events are for G.3 usage, cannot-help, and redirect-rate analytics.

## Event types

- `ask_nevo_question_student`
- `ask_nevo_question_teacher`
- `ask_nevo_cannot_help`
- `ask_nevo_redirect_used`

## Privacy contract

Ask Nevo question signals store category and context only. They reject full
question text fields such as `question`, `questionText`, `fullQuestion`,
`prompt`, `message`, or `text`.

Student question categories:

- `comprehension`
- `vocabulary`
- `navigation`
- `general`

Teacher question categories:

- `student_insight`
- `class_pattern`
- `lesson_recommendation`
- `communication_help`
- `general`

## Product intelligence measures

These signals support:

- usage rate per role
- cannot-help rate per page
- redirect rate
