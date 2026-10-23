# Comprehension ruling: backend delivery and frontend contract

Authoritative inputs: Lydia's 23 October comprehension ruling and the subsequent ruling comment on SCRUM-283. The comment settles evaluation: structured choices/constructions, server-held answers, no model judgement of a child's free text, and panel completion never unlocks the original check.

## Implemented

- In-lesson checkpoint and calculation-step passes gate forward progress and completion. No attempt limit or teacher override. Assessment answers do not gate completion or automatically reopen/reroute a completed lesson.
- Module-local, zero-based cursors are mapped to the ordered lesson sections before checking the gate. Leaving remains possible; an exit cannot save a forward bypass.
- The first server-marked miss returns re-teaching immediately, independently of adaptation confidence, cooldown and prior history. Available formats come from the same cleared-assets list as the player. No nonexistent image/audio is offered.
- Re-teaching rotates through the available formats, approved Simplify, simpler display, slower pacing, smaller source-backed screens and structured guided steps where authored. The child retains format choice; format/Simplify offers require choice and do not overwrite persisted preferences.
- Authored hints remain available after two misses. The hint is also carried in the re-teaching/proactive payload; it must not be hidden solely because the action is a pacing or chunking action.
- Re-teaching passes are recorded as supported. They do not fade support, but are correct passes rather than failures. Three distinct unaided successes remain the fading threshold. Original inference confidence, signal-confirmation, dwell, cooldown and shift-cap constants are unchanged.
- Repeated unresolved support produces a deduplicated teacher notification against the child, falling back to an active school administrator if no teacher mapping exists. It never grants a pass.
- Break offers persist, manual breaks are always available, and immediate frustration/struggle relief coexists with the existing time-based offers. Escalation offers a short pause, a full break, then stopping for the day. Only accepted starts count as prior breaks, not repeated offers/polls.
- Stopping ends the sitting without completing the lesson. Pending support and the unresolved concept survive into the next sitting, as do genuine earlier section passes. Depth/pacing still reset with a new sitting.

## Changed response contract

`POST /api/v1/lessons/{lessonId}/attempts` returns:

- `supportStatus`: independent or supported.
- `comprehensionGate`: required, canAdvance, segmentId, questionIds, unresolvedQuestionIds, reteaching, assessmentGates=false and teacherOverrideAllowed=false.
- `reteaching`: availableRoutes, recommendedRoute, presentation, source-backed screens, optional authored hint, teacherNotified and breakAvailable.
- `advanceAfterHandoff` is now always false. Completing the panel returns to the original check.

Routes carry an action, label, optional format and requiresChoice. Presentation carries low density, one item per screen, slow pacing and recheckRequired; approved simpler text can be included. Apply these rendering settings while presenting the named alternatives, rather than forcing the child into a suggested format.

`POST /api/intelligence/adapt` also returns comprehensionGate and keeps the existing proactiveAdjustment transport. Added actions: offer_modality_shift and rechunk. Added fields: suggestedModality, guidedSteps and requiresChoice. Preserve active help on retain. On a marked miss these responses do not wait for the previous confusion grace deadline. Guided steps carry structured options rather than generic strings.

`PUT /api/v1/lessons/{lessonId}/progress` refuses a forward/completion/check-entry bypass with 409 `comprehension_check_required`; `detail.gate` carries the unresolved section and support. Saving the current allowed position, returning to an earlier section and leaving remain possible. Do not treat this refusal as a network failure to retry indefinitely.

`GET /api/v1/lessons/{lessonId}/sessions/{sessionId}/comprehension` returns the typed gate for reload/resume. Student-owned session and confirmed consent are required.

## Guided panel

Lesson checkpoints gain `guidedSteps`: each has id, prompt, answerType, options and a held answerKey. Supported types: single_choice, multiple_choice, numeric and boolean. Choice keys must match options. IDs must be unique. Option ordering is stable per pupil/question/step and independent of which option is correct.

`POST /api/intelligence/guided-questions/answer` accepts studentId, sessionId, questionId, promptId and answer (legacy option remains accepted). responseLength and outcome never decide correctness. It returns correct, the current/next public prompt, panelComplete, retryCheck and canAdvance=false. Wrong answers repeat the current step; future steps are refused with 409 guided_step_out_of_order. Missing or unrelated prompts return 404; missing structured answers return 422. No model is called to mark a child.

Legacy prose-only guidedQuestions are not magically markable and are not used as an assessment. Historical lessons need re-parsing or authored structured steps to gain this panel; the other support routes and original marked check remain usable. Generated steps arrive through the existing upload safety and lesson-review path, not live model evaluation of a child's answer.

## Break control

`POST /api/v1/lessons/{lessonId}/sessions/{sessionId}/break`

Body: action=start|return|stop_for_day, optional breakType=micro|movement|consolidation|full|stop_for_day. The response gives status=paused|learning|stopped and resumeSegmentId. Repeating stop is idempotent. Breaks never mark a question correct.

Adapt breakSuggestion adds alwaysAvailable=true and offerPersistent. `signals.frustrationDetected` is an optional device-derived transient boolean, not raw touch data or a stored learner label. Only the offered action is retained; the cue/affective trigger is not persisted in that offer. Existing signal ingestion also accepts stop_for_day and student_request.

Baseline before this change: micro, movement, consolidation and full were selected from time, engagement, comprehension, repeated-error/replay and persistent-stall rules. The backend did not enforce fixed durations for those kinds. No unapproved durations have been invented here.

## Offline and deployment

OfflinePackage adds typed comprehensionPolicy. Checks and structured guided steps carry the data required for deterministic local marking. In-lesson checks gate; final assessment does not; panel completion never unlocks; leaving/breaks remain available. Sync answers before forward progress. The server re-marks answers and refuses unsupported progress on sync. Browser/offline enforcement still requires Yinka's frontend implementation; backend testing does not certify it.

No new database migration is required: durable support/guided/break state uses the existing sitting delivery JSON and answer records. Schema head remains 0114. Deploy the backend and coordinate the player contract changes; do not describe a push as a confirmed deployment.

## Actual verification

Real local HTTP against the configured shared database, using clearly named synthetic lessons and existing synthetic accounts, verified: first-miss support; forward and cross-module refusal; structured wrong-step re-prompt; out-of-order refusal; correct panel completion without unlocking; cycling beyond three misses without bypass; supported versus independent passes; completion refused while a second checkpoint remained unanswered; final assessment wrong without preventing completion; completed review mode; pause/return/stop; idempotent stop; pending concept/support carried into a fresh sitting; leaving allowed; staff unable to use the student's gate read; offline policy delivery.

A fresh Gas Exchange upload reached review-ready in 119.9 seconds. Its four generated checkpoints each contain two structured guided steps, confirmed from stored rows. Images/narration were not required for review readiness, and fresh provider recovery is not claimed.

The stored sweep found 378 quick checks and 79 assessments at the time of the read: the same five unmarkable fallback questions, with no additional checkpoint failures. A separate calculation check repaired a legacy metadata mismatch (text/hex input incorrectly labelled choice with no options); all 38 stored steps across 12 calculation sections then validated without changing answers. Later synthetic uploads add records to these totals.

The five quarantined imports remain a content decision, not invented repairs: 166a173f-ffe3-476a-abc0-8eb95695d0e6 (CS2800 Chapter3), and 5c6d3998-3c38-4eb6-84e9-894dd5bb5309, 92e17dd3-8d50-42cf-92bd-b609e8bfd77a, ce9e0224-4f3d-4ced-bc5f-60f8681cd4fc, f51222e2-e6c9-4269-aaee-3f1f8d2c3cce (CSC324 Formal Specification Z Exam Guide). Each has a Page 1 fallback text question with neither an answer key nor options. They stay quarantined pending re-author/drop decisions.

No frontend files or test files were written. Existing test-file edits from the other tool were left untouched and are not part of this commit. No claim is made that the automated regression suite or the frontend offline experience was verified.
