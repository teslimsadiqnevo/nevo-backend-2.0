# Student App Backend Contract

This note records the backend decisions that close the September 2026 student-app blockers.
Swagger remains the field-level source of truth.

## Pre-auth onboarding

1. `POST /api/v1/connections/class-code` accepts a JSON body. Send either
   `{"classCode":"MAP4KZ"}` or `{"classId":"...","schoolCode":"..."}`.
2. Without a bearer token it returns a 20-minute, one-use `onboardingToken`, plus `classId`
   and `schoolCode`. With a student bearer token it enrolls that student directly.
3. `POST /api/v1/auth/pin` accepts `pin`, `onboardingToken`, `firstName`, optional `lastName`,
   and optional `age`. It creates the student, enrolls them in the selected class, returns the
   server-issued `loginIdentifier`, and returns a live auth `session`.
4. Student PINs are exactly six digits. The login, PIN update, invitation acceptance, and
   OpenAPI contracts all enforce the same length.

The frontend must retain the onboarding token only for the current tab and replace its derived
name-based identifier with the `loginIdentifier` returned by PIN completion.

## Messages

Students reply through `POST /api/messages/threads/{threadId}/reply` with
`{"content":"..."}`. The backend permits a reply only when that student can already read the
thread. The existing recipient enum remains for staff creating student or class conversations.

## Lesson player

Lesson segments now expose typed `textVariant`, `visualVariant`, `audioVariant`,
`interactiveVariant`, and `calculationVariant` objects. Generated narration is produced by
YarnGPT, stored in Supabase Storage, and referenced through `audioVariant.storagePath` and
`audioVariant.audioUrl`. Private URL refresh uses `POST /api/content/media/url`.

Each comprehension checkpoint has an id, concept link, prompt, answer type, options, answer key,
explanation, and position. Newly parsed lessons create or reuse the linked concept. Older content
without a recoverable answer remains explicitly `answerKey: null` and should be sent for teacher
review rather than guessed.

## Signals and progress

`LessonSessionRequest.lessonId` is optional. Non-lesson batches set `sessionType` to
`onboarding`, `profiling`, or `sso`; lesson batches use `lesson`. The endpoint remains student
authenticated, so pre-auth events are flushed after PIN completion returns its session.

Student progress responses include backend-authored `reflection` and `highlights`. They use only
recorded practice, lesson, and mastery aggregates and avoid diagnostic language.

## Reviews

`GET /api/scheduler/due-reviews/{studentId}` includes `lessonId` when a playable lesson is linked
to the concept. Send completed review outcomes to `POST /api/scheduler/record-review`; it owns
FSRS memory scheduling. `POST /api/intelligence/scaffolds/attempt` is only for a step inside the
progressive mathematical co-construction experience and owns scaffold fading, not review timing.
