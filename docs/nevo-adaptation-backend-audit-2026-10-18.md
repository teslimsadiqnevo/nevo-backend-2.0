# Nevo Adaptation: Backend Status and Gaps

> **Implementation follow-up, 18 October:** Backend fixes have since been implemented and tested locally. See [the implementation handoff](adaptation-backend-fixes-2026-10-18.md) for current contracts, verification, deployment requirements, and remaining frontend/product acceptance limits. The audit below preserves the original findings against the inspected commit; it is not the current implementation status.

Audit date: 18 October 2026  
Code inspected: `main`, commit `d884acd4a216be34d3b6a15a296b16490c90dcaf`  
Source: **Nevo_Adaptation_Test_Checklist_17Oct fixed.md.pdf**, all 10 pages.

## Bottom Line

**The backend has substantial adaptation machinery, but it does not yet satisfy this checklist end to end.** The document's statement that "the API is sorted" is not supported by the current implementation.

The strongest implemented pieces are local adaptation rules, calculation delivery contracts, progressive calculation scaffold fading, stored answer attempts, lower-depth rerouting, reading chunks, daily warm-up selection, and spaced-review calculation.

The important gaps are the connections between those pieces: four-module onboarding is not enforced before lessons; probe placement does not select starting content; mastery does not drive curriculum progression or prerequisites; hints and Socratic questions do not reach the adaptation engine through its public request path; and inferred accommodations do not reach the session-start configuration through the same source of truth.

There is also a **reproduced quiet-case defect**: steady comprehension and engagement at baseline can produce an automatic `expand` action.

**This is a code-and-focused-test audit, not a production acceptance sign-off.** No frontend files were changed, no live student records were changed, and no paid AI/media calls were made. Production deployment, database state, browser rendering, and a real new-child journey were not verified during this audit.

## How to Read the Statuses

- **Supported:** the relevant backend capability exists; this does not certify the browser journey.
- **Partial:** useful implementation exists, but a required connection, guarantee, or scenario is missing.
- **Gap:** the requested backend behaviour is absent or contradicted by the inspected path.
- **Frontend verification:** primarily a rendering or interaction requirement that cannot be signed off from this backend audit.
- **Retired:** deliberately excluded by the corrected checklist.

## Priority Gaps

### 1. Four-module onboarding is not a server-enforced lesson gate

**Priority: P0. Checklist: opening gate and scenario 1.**

The school-code/Student-ID lookup and first-PIN route exist. First PIN and a teacher-cleared PIN have distinct routing states. Setting a PIN issues an authenticated session, so an authenticated domain probe can be called after that point.

However, `start_lesson_session` checks the student's access to the assigned lesson, not whether all four onboarding modules have completed. The session-state read explicitly supports `configured: false` with defaults. Baseline submission also does not require evidence that all four modules ran. A missing baseline therefore does not prevent lesson entry.

The subject probe is authenticated and requires a subject ID; subjects with no bank items return `noItems`. That is a real empty state, not proof of a completed fourth module.

**Needed:** a defined four-module completion record, a way to resolve the required subject/probe after first PIN, a policy for an empty probe bank, and a shared server gate on learning entry. Then run the exact new-child browser journey.

Evidence: [entry lookup and PIN flow](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/student_entry.py:419), [lesson entry](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/product_learning.py:1110), [default session state](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/insights.py:493), [baseline trials](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/frontend_unblockers.py:1940).

### 2. Proactive hints and Socratic help are not reachable through the adaptation API as written

**Priority: P0 for the demo. Checklist: 8 and 9.**

The engine has `offer_hint` and `show_socratic_panel` branches. Both require `ContentSegment.hints` or `ContentSegment.guided_questions`.

But `ContentSegmentRequest` declares neither field, `_segment_from_request` populates neither, and `adapt_lesson` does not load help from the stored calculation. Consequently, API-created engine segments contain empty help tuples. Supplying extra `hints` and `guidedQuestions` in a request does not repair this: they are ignored by the request model.

The direct engine tests pass because they construct domain segments with help explicitly. They do not prove that the HTTP route can produce those same responses.

A separate answer-attempt path does return generic Socratic prompts after three wrong attempts on one question. That is useful, but it is not the checklist's proactive misconception/stall mechanism.

**Needed:** resolve authoritative hint/question content from the stored lesson in the adaptation request path; add route-level positive and quiet-case tests. Define misconception evidence separately from a wrong-answer count.

Evidence: [request segment schema](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/intelligence.py:50), [request conversion](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/intelligence.py:827), [engine help branch](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/intelligence/adaptation.py:593), [separate attempt handoff](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/product_learning.py:540).

### 3. The quiet-case test fails: ordinary correct work can cause automatic expansion

**Priority: P0. Checklist: quiet half of every scenario, and 7.**

Reproduced locally without a database or model call:

```text
comprehensionScore = 80
sessionAverageComprehension = 80
engagementScore = 0.7
engagementBaseline = 0.7
consecutiveErrors = 0
replayCountOnSegment = 0
currentSegmentElapsedSeconds = 300
availableDepths = [simplified, expanded]

Actual: proactiveAdjustment.action = expand
Actual confidence: 0.68
```

Equal-to-average comprehension plus no errors/replays supplies two positive categories. The positive branch accepts two signals, unlike the three-signal negative branch. It does not require engagement above baseline in this case.

This is an automatic content-change instruction, not the quiet withdrawal of support specified in scenario 7. It does not itself prove that the retired "harder" pill is rendered, since that is frontend behaviour.

**Needed:** distinguish normal successful work from a reason to change content; make the quiet-case test a mandatory route/service regression. Keep support fading separate from automatic expansion.

Evidence: [positive adjustment branch](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/intelligence/adaptation.py:637), [positive evidence](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/intelligence/adaptation.py:883).

### 4. Mastery is an estimator, not a connected curriculum-selection engine

**Priority: P1. Checklist: 1, 2, 3, 4 and 5.**

- The domain probe records answers and returns a per-subject `entryPoint`, but no downstream lesson selector consumes that output.
- Mastery seeding reads `baseline_profile.theta_domain`; the probe route does not write that key. The normal baseline builder does not generate it either.
- The student dashboard serves assignments and recent progress, not a mastery-selected next concept.
- There is no prerequisite relationship in the inspected `Concept` model or prerequisite gate in lesson entry.
- Saving a lesson answer does not automatically call the mastery service or create a spaced-review schedule; those are separate API operations.
- The mastery update accepts correctness and text density, but no response time. It cannot distinguish a considered answer from an instant lucky tap.
- Separate reading and conceptual estimates are implemented. A text-heavy failure preserves conceptual mastery when reading is already low; borderline reading uses mixed attribution, so conceptual mastery can still fall.

**Needed:** connect server-marked attempts to mastery; consume subject probe placement; define mastery completion and prerequisite rules; select eligible new/review work; create initial review schedules when concepts are learned; include timing/evidence sufficient to discount guessing.

Evidence: [probe completion](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/probe.py:122), [mastery seeding](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/mastery/repositories.py:39), [mastery update contract](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/mastery.py:27), [mastery mathematics](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/mastery/engine.py:56), [concept schema](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/db/models/frontend_support.py:24), [dashboard selection](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/product_learning.py:1500).

### 5. Inferred accommodations and session-start delivery have different sources

**Priority: P1. Checklist: 24, 25 and 26.**

The UDL engine requires at least three aligned patterns across five completed sessions. The repository counts sessions, not distinct lesson IDs, so five sittings of one lesson can satisfy that count. Numerical accommodation requires five maths sessions.

The post-lesson worker infers accommodations and writes dated `AccommodationChange` entries. But `/api/session/state/{student_id}` reads active accommodations from `User.engine_config['accommodations']`. No production writer for that key was found in the inspected code. The baseline config builder does not populate it. The inferred result can therefore be logged while the normal session-start read still returns no active accommodations.

The standalone accommodation read recomputes patterns on demand; it is not a session-frozen snapshot. There is no shared guarantee that every read during a sitting returns the same accommodation set.

There is also a specification mismatch: the checklist describes a change the next day after one session, while the implemented historical rule requires five confirming sessions. This needs an explicit product decision, not silently weakening the confirmation rule.

The typed engine config has shorter-text and stepwise-number directives, but not the complete larger-type/line-spacing/softer-contrast bundle described here. Rendering remains frontend work.

**Needed:** one authoritative accommodation result applied at the next session boundary, a frozen per-session delivery snapshot, agreement on five lessons versus five sessions versus the checklist's one-session example, and an explicit rendering contract. Do not turn this into a diagnostic student label.

Evidence: [confirmation rules](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/intelligence/accommodations.py:10), [aggregation](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/intelligence/accommodation_repositories.py:17), [post-lesson logging](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/learner_profiles/post_lesson_worker.py:104), [session-state source](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/insights.py:513).

### 6. Support fading exists for calculation problems, not as a universal segment ladder

**Priority: P1. Checklist: 6 and 7.**

The scaffold engine moves through `full_support`, `partial_support`, `hints_only`, and `independent`; three qualifying correct problems fade one rung, and struggle restores one rung. It stores state and problem logs.

However, the generic adaptation response's segment scaffolding is derived from profile/channel settings, not this live problem-state ladder. There is no demonstrated unified mechanism that makes four support circles change across arbitrary reading and maths segments from the checklist's signal sequence.

**Needed:** connect observed attempts to the correct scaffold state and define how that state drives general segment support. Verify both rising and fading in the actual player, without support-change announcements.

Evidence: [fading engine](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/intelligence/scaffolds.py:18), [attempt API](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/intelligence.py:761), [generic segment support](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/intelligence/adaptation.py:467).

### 7. Guardrails exist, but some depend on optional client inputs

**Priority: P1. Checklist: 8, 10 and 27.**

- The engine defines 90-second modality dwell, 120-second cooldown and three modality shifts per session, with suppression logging.
- Rate-limit application runs only for `mode: in_lesson`; the API defaults to `lesson_load`.
- Session history protection requires `sessionId`, which is optional. Dwell enforcement depends on supplied elapsed time, also optional.
- The higher 0.70 confidence threshold follows a positive modality-shift count, not every earlier adaptation of any kind.
- Break monitoring uses time, engagement, comprehension, errors and replays; it does not implement the specific "stall continues past two adaptations" sequence.
- Lower-depth rerouting happens after completion when the latest marked answers all failed. It does not require two previous adaptations, and does not verify that the lesson has a simpler rewrite available before returning `depth: lower`.

**Needed:** validate the actual lesson/session and derive guardrail history on the server; make in-lesson requirements non-optional where applicable; define the two-adaptation stall/reroute sequence and a safe fallback when lower-depth content is absent.

Evidence: [rate-limit constants and service](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/intelligence/adaptation.py:38), [request defaults](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/intelligence.py:190), [threshold selection](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/intelligence/adaptation.py:942), [break rules](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/intelligence/breaks.py:9), [reroute creation](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/product_learning.py:1336).

### 8. Content contracts support the controls, but do not prove their educational guarantees

**Priority: P1. Checklist: 13, 14, 15, 17, 18 and 21.**

The latest commit correctly preserves generated depth variants when media results are merged. Simplify and Expand have separate stored bodies; Slower can use server-authored reading chunks without deleting source text. Calculation payloads carry steps, values, tokens, stable targets and five scaffold kinds.

However:

- Rewrite acceptance checks length and invented numbers, not full semantic coverage or topic equivalence. It cannot prove "Simplify loses nothing" or "Expand introduces no topic".
- Rewrites can be absent after a failed/rejected generation, for short source text, or on older lessons. A backfill script exists; its execution against all deployed lessons was not verified.
- `_servable_adjustment` only withholds unavailable rewrites when the client supplied `availableDepths`; it does not fetch stored availability itself.
- Reading chunks preserve paragraph/sentence text, but are not individually sized per child and an authored long paragraph is not necessarily split into smaller pieces.
- Modules are accepted only when model output gives valid complete coverage. Invalid/missing module output can yield no modules; six segments do not force a named-module fallback.
- Calculation scaffold is optional. Unknown/invalid scaffold kinds are dropped during parsing, allowing degraded delivery, but a visual scaffold is not guaranteed on every calculation.
- Calculation answers and the solved equation are present in the delivery payload, with hide/reveal metadata. The server supplies values; the client must still enforce when they appear.

**Needed:** content acceptance tests with teacher-authored reference material, explicit missing-variant handling, a named-module fallback for long lessons, and player tests for reveal timing and unknown-kind degradation.

Evidence: [depth merge fix](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/content_parsing/service.py:657), [rewrite checks](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/content_parsing/depth.py:105), [reading chunk construction](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/content_parsing/chunks.py:6), [module validation](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/content_parsing/service.py:936), [calculation contract](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/lesson_contracts.py:306).

### 9. Child-facing wording and lesson-only Ask Nevo exclusion are not universal backend guards

**Priority: P1. Checklist: 12 and 29.**

The Zero-Tag model-response policy checks diagnostic terminology. It is not the checklist's broader child-copy policy against words such as "level", "score" and "struggling" on every surface.

For example, the scaffold decision has a `studentMessage` saying "Support level kept steady for the next problem." Adaptation/break reasons also carry operational descriptions that should not be rendered verbatim to a child. This is a payload/copy risk, not evidence that the frontend currently displays those fields.

Ask Nevo supports contextual requests, but its request/service path does not reject a student's `lesson_player` page. Removing the in-lesson entry point is a frontend responsibility; a server-side exclusion, if required as a hard product rule, is absent.

**Needed:** distinguish internal explanations from approved child-facing text; remove conflicting student-message copy; verify all rendered child copy; decide whether the Ask Nevo exclusion is UI-only or enforced on the API too.

Evidence: [scaffold message](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/intelligence/scaffolds.py:69), [Zero-Tag policy](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/ai_gateway/compliance.py:20), [Ask Nevo service](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/ask_nevo/service.py:153).

## Complete Checklist Matrix

### Opening Gate

| Requirement | Backend status | Current position |
|---|---|---|
| New child: school code, Student ID, first PIN, four modules, Home, lesson | **Partial / launch gate unproven** | Entry and first-PIN contracts exist; four-module completion is not enforced server-side. No fresh browser E2E was run. |
| Every mechanism has a quiet half | **Gap** | Some negative tests exist, but the steady-work reproduction above emits `expand`. Passing component tests do not cover every real request path. |

### Part One: What Content Arrives

| # | Scenario | Backend status | Gap or verification still needed |
|---|---|---|---|
| 1 | Different baseline results start at different subject points | **Gap** | Probe placement exists, but is not connected to next-content selection or per-subject mastery seeding. |
| 2 | Mastery rises, new work stops repeating, review begins | **Partial** | Estimates rise and review schedules work when explicitly recorded; automatic attempt-to-mastery-to-selection-to-review progression is absent. |
| 3 | Instant lucky guesses do not establish mastery | **Gap** | Mastery has no response-time input or guess-evidence gate; correct fast taps are treated like considered correct responses. This is not a claim that two taps from the default seed always cross a mastery threshold. |
| 4 | Reading difficulty does not depress maths | **Partial** | Separate concept/reading tracks and low-reading attribution are tested; ordinary lesson attempts do not automatically invoke that model, and mixed attribution can lower both tracks. |
| 5 | Prerequisites come first | **Gap** | No prerequisite graph/enforcement or mastery-driven next-work selector was found. |

### Part Two: Engine-Initiated Support

| # | Scenario | Backend status | Gap or verification still needed |
|---|---|---|---|
| 6 | Support rises automatically during struggle | **Partial** | Multi-signal rules and per-problem scaffold recovery exist; a unified live support ladder for reading and maths segments is not demonstrated. Two errors alone need not pass the multi-signal gate. |
| 7 | Support quietly withdraws during success | **Partial / conflicting behaviour** | Calculation fading works after three qualifying correct problems; generic adaptation can issue `expand`, including in the reproduced quiet case. The retired harder-content pill must not be restored. |
| 8 | Unrequested hint, then optional break after continued stall | **Gap in public adaptation path** | Hint content does not reach the engine through the API; the specific two-adaptation stall sequence is not implemented. Break threshold computation exists. |
| 9 | Misconception gets Socratic help and a way forward | **Partial** | Three wrong attempts can produce a handoff with `advanceAfterHandoff: true`; proactive guided questions are unreachable through the normal adaptation conversion, and misconception classification is not implemented. |
| 10 | Failed version is replaced by a simpler route | **Partial** | Completion can return a new lower-depth session and later session starts resume it. The decision is based on all latest marked answers failing, not two unsuccessful adaptations; simpler content is not guaranteed. |
| 11 | Anxiety screen softening | **Retired** | Excluded as instructed. Do not add it as an accommodation/demo requirement. |
| 12 | Nothing diagnostic or evaluative is named to the child | **Partial / frontend verification** | Diagnostic-response filtering exists; the broader all-surface wording guarantee is not enforced and `studentMessage` contains "level". |

### Part Three: Child Controls

| # | Scenario | Backend status | Gap or verification still needed |
|---|---|---|---|
| 13 | Simplify preserves the whole idea | **Partial** | A separate simplified body is generated and now retained. Semantic completeness is not mechanically verified; key points are not a substitute. |
| 14 | Expand deepens without changing topic | **Partial** | Separate expanded body and numerical checks exist; topic/meaning fidelity still needs content acceptance testing. |
| 15 | Slower breaks up the same text | **Supported with limits** | Stable reading chunks preserve source prose and the slower action is reachable; paragraph size and tap-to-continue behaviour need checking in the player. |
| 16 | Chosen version holds within a lesson, resets afterwards | **Frontend verification** | Depth telemetry and variants exist, but the backend does not enforce a lesson-scoped manual depth preference. Check the player's state lifetime; do not add a persistent student label. |

### Part Four: Calculation

| # | Scenario | Backend status | Gap or verification still needed |
|---|---|---|---|
| 17 | Child builds each thinking step; no complete answer early | **Supported contract / frontend verification** | Steps, targets, `assembles`, hidden result tokens and full equation are supplied. Early answer hiding depends on the renderer; scaffold content is optional. |
| 18 | All scaffold kinds draw correctly; unknown kind degrades | **Supported contract / frontend verification** | Drawing kinds: `bar`, `number_line`, `dots`, `array`, `place_value`. Build-piece aliases normalise separately. Invalid kinds are dropped at parse time; drawings and degraded UI need visual tests. |
| 19 | Completing a build does not automatically submit | **Frontend verification** | Backend supplies build targets/counts; confirming is a player interaction, not guaranteed by the API. |
| 20 | Values originate on the server | **Supported contract** | Steps, answers, scaffold values, piece counts and equation states are delivered as data. Confirm the frontend does not derive missing arithmetic. This does not mean every tap requires a server round trip. |

### Part Five: Longer Shapes

| # | Scenario | Backend status | Gap or verification still needed |
|---|---|---|---|
| 21 | Long lesson has named modules and calm boundaries | **Partial** | Module data, recap and preview exist; invalid/missing module coverage can become an empty module list. No unconditional six-segment grouping guarantee. Boundary visuals and progress wording are frontend checks. |
| 22 | One rotating daily warm-up, about 45 seconds | **Supported core / partial** | Stable UTC-day dimension rotation, account-held completion and server-marked domain items exist. Other days declare device tasks. Duration, delivery and whether responses recalibrate learning beyond the recorded warm-up are not established by this route. |
| 23 | Spaced review returns concepts | **Supported scheduler / partial integration** | Due-review API and daily refresh exist; initial successful review is due in about 1.76 days. Completing a concept does not itself create the initial schedule. The review lesson and closing copy need browser verification. |

### Part Six: Across Sessions and Modality Offers

| # | Scenario | Backend status | Gap or verification still needed |
|---|---|---|---|
| 24 | Reading rendering changes next session and stays stable | **Partial / disconnected state** | Multi-session inference and dated change log exist; the normal session-start read uses a different stored source. Five-session confirmation also differs from the one-session example. |
| 25 | Attention support carries into next session | **Partial / disconnected state** | Attention inference exists but has the same delivery-source problem; no complete contract for shorter segments and new pause screens. |
| 26 | Numerical work becomes visual while notation remains | **Partial / disconnected state** | Maths-only inference and authored numerical scaffolds exist; inferred state is not reliably delivered by session start, and a stepwise flag does not generate a missing visual. |
| 27 | Other modality is offered only when warranted and within limits | **Partial** | Availability, declines, multi-signal confirmation, cooldown and shift caps exist. Optional session/timing inputs and request mode weaken unconditional enforcement. Provider availability can leave no alternative. |
| 28 | Accepting an offer swaps primary/secondary rather than stacking | **Frontend verification** | API returns a suggested modality and tracks acceptance/outcome. Actual primary/secondary layout changes happen in the player. |
| 29 | Ask Nevo absent mid-lesson; contextual elsewhere | **Supported contextual chat / frontend verification** | Page/context handling exists; hiding the entry point must be verified in the frontend. API does not enforce a lesson-player exclusion. |

## Part Seven: Regression Items

| Regression | Backend position |
|---|---|
| Filled PIN box is navy, even after an error | Frontend-only colour/state check; not certified here. |
| No child-facing "tablet" wording | Frontend/content-copy check. API form-factor enums can legitimately contain `tablet`; they must not be rendered as child-facing copy. |
| Never claim saved without confirmation | Progress/answer writes commit before successful responses. Offline queuing, error handling and save notices remain frontend acceptance checks. |
| Browser Back is never the only exit | Frontend navigation check. |
| Lesson chips appear only over text | Frontend visibility check; depth controls must also have actual variant bodies available. |
| Preferences follow the child across devices | Account-backed settings read/write exists; verify that the frontend reads it on a second device. This is different from lesson-only depth choices. |
| Offline lessons carrying checks can complete | Offline package includes modules, explicit nullable recap, assessment, segment checkpoints and depth variants. Stored attempts support client attempt IDs for retry. Local completion and later replay/sync need a browser/offline test. |
| Socratic panel hands off on server instruction | Attempt response carries handoff prompts and `advanceAfterHandoff: true` after three misses. The proactive-help API gap still applies. |
| Account Closed cannot resume; shared-device escape exists | Auth checks account status; closed state has a dedicated error vocabulary. Browser history/session clearing and the escape link are not verified here. |
| DOB disagreement is a note, never a block | Backend explicitly returns `blocksAccess: false`; the age-check blocking compatibility hook always returns false. Do not confuse this with a consent-withdrawal refusal. |

Evidence: [offline package](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/product_learning.py:2473), [stored attempts](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/product_learning.py:1183), [account settings](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/frontend_unblockers.py:2592), [age non-blocking rule](/Users/teslimcodes/Developer/nevo-backend-2.0/src/nevo/api/age_checks.py:83).

## Tests Run in This Audit

**Total: 157 tests executed, 156 passed, 1 failed.** These were focused local tests, not the complete suite or a live acceptance run.

First batch: **102 passed, 1 failed** across adaptation, scaffold fading, breaks, UDL, mastery, review timing, probe selection, PIN states, calculation payloads, reading evidence, student support contracts and depth rewrites.

The failure is `tests/test_calculation_scaffold_contract.py::test_the_scaffold_carries_what_the_drawing_needs`: its exact-dictionary assertion expects the older payload without `start`, `markIds`, `labelIds`, and `pieceIds`. Actual output contains those newer fields. It appears to be a stale expected contract, not evidence of broken drawing arithmetic; it still leaves this selected suite red and needs updating deliberately.

Second batch: **54 passed** across student response contracts, adaptation payload validation, UDL schema checks, entry contracts and the accommodation/scaffold/scheduler/mastery API tests. These use local contract or fake-service checks and do not validate the production database.

Additional safe reproductions:

1. Steady, correct work at baseline produced `expand`, confidence `0.68`.
2. Converting an API segment containing `hints` and `guidedQuestions` produced empty `hints` and `guided_questions` on the domain segment.

No database integration tests were run because a separate disposable database was not established. No production migrations, data repair, provider top-up or frontend changes were performed.

## Provider and Deployment Limits

- Last reported YarnGPT state was `402 QUOTA_EXCEEDED`; the adapter can pause/retry appropriately, but cannot restore account quota. Recovery was not verified in this audit.
- Last reported OpenAI image state was exhausted credit; Lydia owns the top-up. Recovery was not verified here.
- Missing media matters to scenario 27: an engine cannot offer an audio/image modality that was never generated successfully.
- The audit includes the 16 October depth-preservation and slower/expand commit. It does not establish that the public API is running that commit or that every older lesson has been backfilled.
- Existing automated tests do not replace the checklist's real browser journey, multi-session tests, child-facing wording review, or deployment/database verification.

## Recommended Order of Work

1. Fix the false quiet-case expansion and add a regression through the public adaptation route.
2. Connect stored hint/guided-question content to the adaptation API; prove hints and Socratic help work without a manual child request.
3. Implement and test the four-module onboarding completion gate, including subject resolution after first PIN and empty probe-bank handling.
4. Unify scaffold state and live segment support so the demo can show support rise and quietly fade.
5. Connect probe placement, server-marked attempts, mastery progression, prerequisite eligibility and initial review scheduling.
6. Unify inferred accommodations with the next session's frozen delivery configuration; settle the one-versus-five-session wording conflict.
7. Close optional-input guardrail loopholes and align stall/reroute sequencing with the checklist.
8. Verify content fidelity, named modules, missing rewrite/media fallbacks and child-safe copy; update the stale scaffold test.
9. Run the checklist in the real frontend with a new child, a quiet child, a struggling child, an offline lesson and a second-session return before signing it off.

## Safe Status to Share

"The backend has the core adaptation rules, scaffold fading, calculation payloads, saved attempts, rerouting, reading chunks, warm-ups and review scheduling. The checklist is not fully passed: the audit found missing connections in onboarding, proactive help, mastery-driven progression and cross-session accommodations, plus an automatic expansion during normal steady work. We need to fix those and run the actual player journeys before calling adaptation ready end to end."
