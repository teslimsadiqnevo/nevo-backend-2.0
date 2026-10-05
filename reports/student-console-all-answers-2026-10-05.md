# Student console: every ask, answered

**Backend → Olayinka** · 5 October 2026 · covers rounds 1 (B1–B36) and 2 (B37–B66)

Round one is closed: 33 asks, all answered or built. Round two: 28 of 30 closed,
2 still open and listed at the end with what each needs.

Verify anything here against `nevo-backend-2-0-kn3d.onrender.com`. Where this
document and the live spec disagree, the spec is right.

---

## Round one — closed

### Built and live

| Ask | What it is |
|---|---|
| B3 | `firstName`/`lastName` on `JoinInspectionResponse` |
| B4 | `age` on `JoinRequest`, stored as a band — **but see B4 below, this path is now gone** |
| B5 | `ageBand` is a closed enum, derived from date of birth |
| B6 | Superseded — see below |
| B8 | Warm-up no longer ships its answer key; the pick is marked on the server |
| B9 | `POST /api/baseline/trials` — trials in, reduction here |
| B10 | `doneToday`/`answeredAt`, held against the account not the tablet |
| B11 | `description` on lesson summary and detail |
| B12 | `media_load_failed` |
| B13 | `system_busy`, `tap_blocked`, `session_context`, three baseline lifecycle types |
| B15 | All three undefined types defined; `ask_nevo` session type added |
| B16 | `format` and `promptAudioUrl` on `ComprehensionCheckpoint` |
| B17 | `ScaffoldingLevel.none` |
| B18 | Hints and the socratic panel now fire — see the ceiling note below |
| B19 | `guidedPrompts` with ids, plus `POST /api/intelligence/guided-questions/answer` |
| B20 | Seven types for hints, step-up and guided questions |
| B21 | `numberProblemsStepByStep` on the engine's support config |
| B24 | `GET /api/session/state/{id}` and a typed `EngineConfig` |
| B26 | `masteredConcepts`, `revisitConcepts`, `resultNote` |
| B27 | Scaffold attempts take the child's answer and are marked server-side |
| B28 | A typed review `outcome` the server scores |
| B29 | `note` on the progress read |
| B31 | Zip declared in the spec, `sizeBytes` measured, `includesMedia` |
| B32 | `canHelp`/`cannotHelpReason` on `AskResponse` |
| B33 | The 429 declared in the spec — it was always raised, just undocumented |
| B34 | Four student notification types |
| B35 | `preferredName`, its own column |
| B36 | `POST /api/v1/client-errors` |

### Answered

**B1 — school SSO.** Off the board, no date. When it returns the provider comes
back as a new field on `SchoolCodeResponse`, not on the auth method. Build for
PIN.

**B2 — the entry link.** Delete it. `accountReady` meant "has a PIN and can sign
in normally", but it does not matter: that endpoint never resolved for anybody.
It refuses any grant that does not name a child and nothing ever wrote one —
production held four grants, none naming a student. Replaced by
`POST /api/v1/student-entry/lookup`.

**B4 — correction.** I built `age` on `JoinRequest` for you, and SCRUM-215 then
removed the student invite path entirely. That field now has nothing behind it.
The `firstName` on the join inspection survives, because invited teachers are
still real. My ordering mistake, not yours.

**B6 — correction.** You closed this because admin resets issue four digits and
return `pinLength: 4`. That endpoint is gone. SCRUM-216 settled that nobody
except the child ever sets a PIN, so `pin/reset` is now `pin/clear` and never
accepts, returns or generates one. The length rides on the clear response and
the session instead. You are right to park `pinLength` until design settles D58.

**B7 — correction.** A withdrawn child does **not** get `account_paused`.
Withdrawal does not deactivate the account, so sign-in succeeds; the refusal is
`403 consent_withdrawn` when they try to start a lesson, record progress, take
one offline or ask Nevo. That is deliberate — the gate is off the reads so the
child can load the screen explaining why learning stopped. Lydia has since
ruled they sign in and see a suspended screen, which is what happens.
`account_paused` is for a deactivated account, a different state.

**B14 — raw touch stays on the device.** The Touch Signal Contract is right. Tap
coordinates and per-element dwell are a finer behavioural record of a child
than anything else we keep, and we would store it continuously for every child.
What the engine needs is derivable, and the two cases being misread as idleness
now have their own types. The privacy layer refuses those field names
mechanically.

**B22 — yes.** A student's own token on their own id already worked; the guard
only refuses a student reading *another* student.

**B23 — the rule, not boundaries.** Split on sentence, maximum three parts,
never mid-sentence. "About 130 words" describes the example, not a limit.

**B30 — not yet.** Under counsel hold. A narrative naming a child and mentioning
modality is written for a teacher and should not be shown to the child as-is. A
real ticket once the hold clears.

### One ceiling worth knowing (B18)

Hints and the socratic panel fire after two wrong answers, then step through if
the child has also gone back over the segment. But hint text exists in exactly
one place in the product — `CalculationStep.hint`. An explanatory segment has no
hint and no guided questions, so the engine returns **nothing** for one rather
than inventing text. Making it work everywhere means generating hints at parse
time.

---

## Round two — closed

### B37 — the signal contracts are published

You were right: `openapi.json` carried 47 names and nothing else, so "it is
documented in the enum" was useless to you. One catalogue now, as data, doing
three jobs:

- rendered into `SignalEventType`'s own schema `description`, which is where a
  generated client looks
- served from **`GET /api/signals/catalogue`** — trigger, payload and a
  `serverWritten` flag per type, so you can assert against it in CI
- a test refuses to pass while any type is missing from it

**Your five payloads are confirmed**, and three are pinned in a test so a later
edit cannot quietly disagree with this answer.

**Two types are server-written and you must not send them:**
`guided_question_answered` and `adaptation_suppressed`. If your client has been
sending either, those counts are currently doubled.

### B38, B39, B41 — answered inside the catalogue

- **`modality_switch_outcome`** fires once the child has spent a full segment in
  the new modality, so there is something to compare. `{from, to, outcome}`. One
  per switch, from the client that made it.
- **A narration restart is `replay`.** `narration_replayed` is marked reserved,
  so there is one home and no double count. Your instinct was right.
- **`guided_question_answered` is written by the answer endpoint** — do not send
  it. **`hint_used`** means the child acted on the hint: opened one they had to
  open, or moved on after one shown in full. A hint shown and ignored is
  `hint_offered` alone. **`outcome: "asked_again"`** when the child asks the
  same guided question again rather than moving on.

### B42 — the four fields are defined, in the spec

Descriptions now reach `openapi.json`, not just the source:

- **`secondsSinceLastAdaptation`** — since the last adaptation was *applied on
  screen*. Not since it was decided, not since the last request. Null when none
  has been applied this session. It feeds the cooldown, so counting from the
  wrong moment makes the engine either too eager or deaf.
- **`sessionModalityShiftCount`** — the whole session, not the current segment,
  however the change came about. It caps how often one session may be
  rearranged; a per-segment count would reset that cap at every segment.
- **`consecutiveErrors`** — a running in-lesson streak, reset by a right answer.
  Exactly what you are already sending. Two in a row is what triggers a hint.
- **`proactiveAdjustmentsCount`** — adaptations the child actually saw applied.
  Not offers, not decisions held back. Leave it 0 if you are not counting; that
  reads as "not reported" rather than "none happened".

### B44 — yes, the stream refuses a withdrawn child

It did not before — the gate was on starting a lesson, recording progress,
taking one offline and asking Nevo, and **not** on the stream. So a client that
missed a withdrawal went on reporting a child nobody may process. Now gated.
Your client stopping the stream is still right; this backs it up.

### B45 — `depthShown` on `time_on_segment`

`standard`, `simplified` or `expanded`, on every segment, not only where an
adaptation changed it. Validated to those three values, because this is read
back as evidence about what a child actually saw and a wrong answer there is
worse than a missing one.

### B46 — `segmentId` on the adjustment

Always the segment the request named. If the engine ever means a different one
it will say so there rather than silently.

### B49 — the check resumes

`checkPosition` on `ProgressWrite` and on the progress response, and
`checkResumableUntil` — the end of the day it was started, sent so two tablets
agree on when it has lapsed rather than each deciding.

To your question: **the attempts are the record of what was answered**, and the
position is the place in the list, which attempts cannot tell you because a
skipped question leaves no attempt behind. You need both.

And yes — the `exited` record plus the assessment attempts is what an
"unfinished check" list reads.

### B50 — yes, a `true` always means the interval lengthened

Checked rather than reasoned, because the screen says something to a child on
the back of it. Two separate guarantees:

**Only an unaided first attempt scores as recall.** `after_hint` and
`second_attempt` both return `recallSuccessful: false`. A child who needed help
remembering needs to see it again sooner, not later.

**A `true` always strictly lengthens the interval.** Stability is multiplied by
a gain that is never below 1.35 and then has 1.0 added, and the due date is
derived from stability — so there is no path where a `true` comes back with the
schedule unchanged or shorter. Measured at the hardest difficulty the model
allows, which is where the gain is smallest:

```
difficulty 10.00   stability 0.500 → 1.675   (strictly greater)
ordinary case      interval  1 day → 3 days
not recalled       interval  1 day → same day
```

So **"You've got this one more firmly now" is safe on a `true`** and no extra
field is needed. Both guarantees are pinned in a test, so neither can change
without something failing.

### B43 — `profiling` is the baseline, and the markers belong on it

Nothing in the product branches on `session_type` today: it is stored and
reported, and the engine reads events rather than session kinds. So this is a
ruling rather than a description of existing behaviour.

**`profiling` is the assessment itself** — the baseline and anything that
measures a child in order to configure the engine for them. **`onboarding` is
the account coming into existence** — entry, the consent check, PIN creation.

So yes: the baseline's module markers (`baseline_module_start`,
`baseline_module_complete`, `baseline_submitted`) should ride a `profiling`
session, not the onboarding sequence's `onboarding` one. They are measurements,
and putting them on `onboarding` would mean a later re-profiling produced
events indistinguishable from a child's first morning.

### B47 — yes to the first, and here is the second

**`POST /api/content/media/url` accepts a student token.** It takes any
authenticated principal with no role check, which is deliberate: a child whose
picture failed to load is exactly who needs a fresh link. A public bucket
returns the stable public URL; a private one returns a fresh signed URL, which
is how a lesson parsed before the last expiry stays playable.

Two error shapes worth handling: `400 invalid_storage_path` for a path that is
not ours, and `502 storage_unavailable` when the bucket itself is unreachable —
the second is worth retrying, the first never is.

**`VisualVariant.previewUrl`** is a much smaller copy of the same picture, for
a card or a list, or to paint something before the full image arrives on a slow
connection. It is `null` on images stored before it existed, so treat absence
as "use `imageUrl`" rather than as an error.

### B51 — the base is zero, and the count is every segment

**`segmentPosition` is a zero-based cursor**, not an ordinal. It is
deliberately not the same counting as a segment's `sequenceOrder`, which is
one-based and is the segment's own number in the lesson. Both were correct and
neither said so, which is why you had to guess.

So the fraction is `segmentPosition / segmentCount`, and a child at position 2
of a 10-segment lesson is on "segment 3 of 10".

**`segmentCount` is every segment in the lesson**, which is every segment a
child plays. `reviewSegmentCount` is a subset of those flagged as needing a
teacher's review before the lesson is published — it is not a second kind of
segment and should not be subtracted.

It is now on `RecentProgressResponse` too, so Home can draw the fraction
without a second read per lesson.

### B52, B53 — Home and the Progress cards

`RecentProgressResponse` carries `title`, `subject` and `segmentCount`, so a
library lesson can appear under "Pick up where you left off".

The progress read carries `topicsDone`, `topicsTotal` and `currentTopic`. A
topic is done when understanding passes the threshold the engine treats as
learned. **The total is topics this child has met, not the curriculum** — a
denominator a child has never seen makes early progress read as failure.
"Working on" is the unfinished topic with the most practice behind it, not the
first alphabetically.

### B54, B55, B65 — the warm-up

- **A device-task day counts.** Send the response with no `itemId` and
  `doneToday` is set. Previously nothing was sent on five days in six, so a
  second tablet offered a second run and took a second measurement.
- **`correct` is gone from the reply.** You were right that the device has no
  need to hold a verdict on a child.
- **`question` and `options` are now optional**, with a `served` flag. Only the
  domain task has a question; requiring them of every dimension made the other
  five look like served questions with nothing in them.

### B57 — there was no limit, and now there is

You were right to ask. The idle timeout slides on **every** authenticated
request, so an open tab polling anything renewed indefinitely. There is now an
absolute lifetime counted from sign-in: **10 hours for a student**, 12–14 for
staff, so one sign-in cannot carry into the next day on a shared tablet. Both
numbers are in the contract.

Note that `POST /auth/session/refresh` never extended anything — it reports the
current deadline. The sliding happens on ordinary authenticated requests.

### B58 — `account_closed`

Its own 401 code. A removed child was being told their school can turn the
account back on, which is not true and leaves them opening the app again.

### B60 — `lesson.json` is not a `LessonDetailResponse`

It is a narrower, differently shaped thing: the variants are nested under
`modalityVariants`, the segment key is `key` not `segmentKey`, and none of the
review or authorship fields are present. A client validating it as a lesson
detail would reject a correct package.

Published as **`OfflinePackage`**, and the builder validates through it, so the
shape the spec publishes is the shape that ships. There is also
`GET /api/v1/lessons/{id}/offline-package.json` — the same payload, so you can
check it without unzipping.

### B61 — a size without committing to a download

`GET /api/v1/lessons/{id}/offline-manifest`. A read, so it records nothing.

Per lesson rather than a field on the list, deliberately: the size is measured
from the real archive rather than estimated, and measuring means building one.
Ask for the lessons you are about to show.

### B62 — guaranteed rather than confirmed

Nothing raises those four yet, so a promise about a value nobody produces would
be worth nothing. Instead the path and title are fixed as data and whatever
eventually raises one takes them from there:

| Type | `navigatesTo` | Title |
|---|---|---|
| `lesson_assigned` | `/student/lessons` | A new lesson is ready for you |
| `review_due` | `/student/review` | Time to go over something again |
| `teacher_replied` | `/student/messages` | {teacher} sent you a message |
| `sign_in_changed` | `/student/profile` | Your PIN has changed |

A test asserts every student type has one and that it starts `/student/`.

### B64 — already built, before you asked

The route you describe exists: **`POST /api/v1/student-entry/pin`**, taking
`schoolCode` + `admissionNumber` + `pin`, returning a session. It was built for
SCRUM-216 and is exactly your "lookup-scoped PIN route".

It only opens while the PIN is unset, so it cannot overwrite a classmate's
credential, and it is gated on consent and the age check like every other door
a child can reach.

Your three sub-questions:

- **`accountReady: true`** — yes, send them to sign in. They have a PIN.
- **`ageCheckPending`** — the school and the parent disagree about the child's
  date of birth. The child cannot start and there is nothing they can do about
  it, so the screen should say Nevo is checking something with their school and
  to come back in a day or two. Never ask the child to resolve it.
- **The baseline before a session** — park it on the device and send it once the
  PIN step creates the session, exactly as now. `POST /api/baseline/trials`
  needs a session; nothing has changed there.

### B66 — the test school

Seeded, and `docs/test-tenant-spec.md` now exists — it did not, so I wrote it as
the shared contract. It documents the fixed points and, for each threshold, the
API limit it sits past.

**Your probe student: login `NV-E2E000`.** Student ID `E2E/PROBE`, PIN `4820`,
in JSS 1A, consent given so tests can reach a lesson. Verified signing in
against Render. The seed script is idempotent.

One thing to change in CI: **the school code is not a fixed point.** It is
generated, because the four-character scheme has to be exercised — and a
hardcoded code broke your tests once already. Read it from the registration
response. It is `D6AM` today.

---

## Round two — still open

| Ask | What it needs |
|---|---|
| **B48** | Marking which text is authored and which generated, plus the simplified wording. Design D30 — needs design before I can serve it. |
| **B63** | Avatar shapes. Waiting on SCRUM-182's redraw; worth aligning then rather than now. |

---

## Two things on our side

**SCRUM-179 / D58.** You are holding off on `pinLength` and `pinChangeRequired`
until design settles the six-digit-child-on-a-four-box-pad question. The backend
half is done and the fields are sitting unused. Worth chasing Lydia, because it
is a frontend blocker resting on a design decision rather than on code.

**Roster observations.** The count / null-count / absent variants are still not
seeded in the E2E tenant. They are derived from lesson sessions rather than
stored, and whether the absent case is reachable at all needs checking before
you build against it.
