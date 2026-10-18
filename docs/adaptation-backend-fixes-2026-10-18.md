# Adaptation Backend Fixes and Handoff

Date: 18 October 2026

Status: implemented and tested, with configured Supabase migrations applied through `20261018_0103`. Backend only. Hosting deployment must be confirmed separately. The original findings remain in `nevo-adaptation-backend-audit-2026-10-18.md` as an audit snapshot.

## What Changed

| Audit gap | Backend resolution |
| --- | --- |
| Lesson entry before onboarding | Shared student learning gate requires all four recorded modules; readiness read resolves enrolled subjects and actual probe availability. |
| Unreachable proactive guidance | Adaptation loads hints, guided questions, scaffold state, and marked errors from the stored lesson and attempts, rather than trusting client-provided content. |
| Expansion during steady work | Positive adaptation requires observed improvement, three aligned signals across at least two categories, and sufficient confidence; steady baseline work stays unchanged. |
| Disconnected mastery and progression | Saved server-marked answers update mastery, scaffold state, and initial review scheduling in the same transaction; next-work selection uses placement, prerequisites, assignments, availability, and due reviews. |
| Conflicting accommodation sources | The next sitting captures one delivery snapshot; session-state and accommodation reads reuse it rather than changing settings mid-sitting. |
| Disconnected scaffold ladder | Distinct marked problems advance or restore support; adaptation reads the current concept ladder. Duplicate submissions cannot count as multiple successful problems. |
| Optional guardrails | Server-validated sessions, server entry clocks, persisted application history, cooldowns, confidence thresholds, and suppression records constrain decisions. Persistent stalls after repeated adaptations can offer a break. |
| Missing content fallbacks | Stored depth availability is checked, missing variants are suppressed, numerical source facts must survive rewrites, long text gets bounded chunks, and long lessons receive complete named module grouping. |
| Child-facing engine language | Delivery explanations use child-facing language; scaffold changes have no support-level announcement. Student Ask Nevo refuses lesson-player use in favour of lesson guidance. |

The existing Slower/Expand implementation was retained while tightening evidence and availability checks.

## Onboarding and Progression

After the existing first-PIN flow issues a student token:

1. Call `GET /api/v1/students/me/onboarding` for `complete`, `modules`, `subjects`, and `nextModule`.
2. Record the existing baseline activities. Module IDs are `grid_span`, `pattern_flanker`, `sentence_dot`, and `domain_probe`.
3. Use a returned subject ID for the existing authenticated probe routes; complete the actual served probe items.
4. Start the assigned lesson after all four modules are complete.

Incomplete entry returns `409` with `detail.code: onboarding_required`, missing modules, and the onboarding destination. An empty probe bank remains a genuine content-not-ready state; it does not silently complete the fourth module. Schools must provide probe items and class-subject mappings.

`GET /api/v1/students/me/next-work?subject=...` returns a due review or eligible new work, with `lessonId`, `conceptId`, `conceptName`, `segmentId`, zero-based `segmentPosition`, and `kind` (`review` or `new_work`), or `null` when none is eligible. The student dashboard also exposes onboarding readiness and next work.

Only assigned, available, non-cancelled lessons are candidates. Prerequisite work is enforced at entry and at target-concept attempts/progress; refusal uses `409 prerequisite_work_required`. Subject placement affects starting selection, not a fabricated mastery result.

Curriculum configuration uses:

- `GET /api/v1/concepts/{concept_id}/curriculum`
- `PUT /api/v1/concepts/{concept_id}/curriculum` with `curriculumPosition` (0–1) and `prerequisiteIds`.

These are school-scoped staff routes. Invalid dependencies and cycles are refused (`422 curriculum_cycle` for a cycle). Existing concepts receive an order backfill; educational prerequisite relationships must be configured by the school, not invented by the backend.

## Attempts and Support

The existing saved-answer endpoint now accepts observed `responseTimeMs` and `hintCount`. Send these with the actual answer. Correct but implausibly fast, missing-required-timing, or hinted answers do not inflate independent mastery.

Server-marked saved attempts update mastery directly: a second mastery write is unnecessary. The legacy student mastery update requires `answerAttemptId` referencing the saved marked attempt and returns its existing mastery rather than counting it again.

Calculation attempts use `source: calculation`: individual steps identify their authored step; a complete problem identifies its segment. Step answers can update mastery, but only the complete problem counts toward problem-level scaffold fading. Three qualifying distinct problems fade support one rung; struggle restores support without negative messaging.

The adaptation response exposes a persisted `decisionId` and typed `suppressedAttempt`. Its decision evidence is distinct from application history: report an adaptation as applied only when the client actually displays/applies it. Offers, outcomes, and break events do not masquerade as applied modality changes.

Student Ask Nevo on `lesson_player`, `calculation_player`, or `student_lesson` returns `409 use_lesson_guidance`; Home/post-lesson use and teacher Ask Nevo remain available.

## Session Delivery Contract

Session start and lower-depth reroute responses carry `deliveryState` and the delivery cursor. `/api/session/state/{student_id}` can take `sessionId` to read the correct sitting's frozen settings. Lower reroute retries return the same rerouted sitting with stronger support, shorter text, and pauses; ordinary reopening resumes it.

A new day or expired sitting creates a fresh sitting and delivery snapshot while retaining the lesson cursor. Same-day unfinished checks retain their sitting and answers.

Typed settings now include reading `fontScale`, `lineSpacing`, and `contrast`, plus support `pauseBetweenSegments` and `numericalVisuals`. The frontend must consume these settings; backend tests do not prove their visual rendering.

Accommodation confirmation still requires at least three aligned patterns over five distinct completed lessons. Five sittings of one lesson do not qualify. Numerical accommodation uses maths evidence. Active delivery state is held on the sitting, not as a persistent accommodation label on the student. Historical evidence and change records are not raw touch streams.

## Content and Acceptance Limits

- Generated depth rewrites require teacher review; checks reject missing source numerical facts and invented numerical facts, but cannot prove arbitrary prose is semantically perfect.
- Missing rewrites produce explicit suppression, not a claimed content change. Existing missing content still needs successful generation and approval.
- Reading chunks preserve source text and offsets while bounding long prose groups. Named module fallback covers all sections of long lessons on parse and read paths.
- Unknown calculation scaffold kinds degrade to step delivery and generate a warning. Answer-reveal timing remains a player responsibility.
- No frontend files were changed. Colour, support-dot rendering, button placement, browser offline synchronisation, and visual modality swaps still need frontend acceptance tests.
- A single-session accommodation example is not a replacement for the five-distinct-lesson safety rule. It can only activate next day if sufficient earlier confirming evidence already exists.
- YarnGPT and image-generation account credits were deliberately not changed or certified recovered.

## Deployment and Verification

Run `alembic upgrade head` before serving the updated code. New migrations:

- `0102`: sitting delivery state, observed answer timing/hints, curriculum order and prerequisites.
- `0103`: adaptation decision evidence, nullable probe declines, source-backed concept links and onboarding evidence backfill.

Historical onboarding is backfilled only where recorded evidence supports completion; unknown old accounts are not falsely marked complete. `not_sure` probe answers remain declines, not incorrect answers.

A clean database migration from base through `0103` passed locally. Endpoint tests use an explicitly opted-in disposable localhost PostgreSQL database, never the configured Supabase database. At the user's subsequent request, the configured Supabase database was upgraded from `20261014_0101` through `20261018_0103`, including the documented evidence-backed data backfills; no endpoint test fixtures were written there.

Verification: the final full non-integration suite passed all 1,660 tests; the focused endpoint/API run passed 23 tests, including 15 real database-backed endpoint scenarios. Ruff passed across source and tests. The only test warning was an existing TestClient/httpx deprecation. Configured Supabase migrations completed; deployed endpoint behaviour and browser acceptance remain separate rollout checks, not claims made by this handoff.
