# Student console: backend answers

**From:** Teslim (Backend) · **To:** Olayinka · **1 October 2026**

Answering all 33 by number. **16 are built and deployed**, the rest are
answered or named as mine to build.

---

## First, a correction that changes your list

Your re-check was against commit `70b14a4`, which is **27 September**. It
predates everything from the 30th and today: the four-character school code,
admission numbers, the import parser, OB-02, the registration fix and the
entry lookup. Worth re-reading the live spec before you scope off this doc —
some of what follows you already have.

---

## Built and deployed (16)

Each of these is live on the temporary host. Wire away.

### B3 — The invitee's name on a join link
`JoinInspectionResponse` now carries `firstName` and `lastName`, from the
invitation itself. Null where the school supplied no name — the roster import
asks for names without insisting on them.

### B4 — Age on a join-link account
`JoinRequest` takes `age` (2–25). It is stored as a **band** on the account,
not thrown away after picking a baseline. Only read for a student, and never
overwrites a date of birth, which is the better source.

### B5 — The age band is now a closed set
`ageBand` is an enum: `early_primary`, `upper_primary`, `junior_secondary`,
`senior_secondary`. Derived from the date of birth on every read, so it is set
for every child the roster has a birthday for, and it stays true as they age.

**You found a real bug here.** Those four names already existed — buried in a
match statement in the mastery engine deciding expected reading speed. Nothing
ever wrote them: both write paths stored `str(age)`, the string `"11"`, so the
match fell through to its default **every time**. Every child has been measured
against the same expected reading speed regardless of age. Fixed, and legacy
`"11"` values are converted on read rather than needing a backfill.

### B10 — "Warm-up done today" across tablets
`GET /api/baseline/recalibrate-prompt/{studentId}` now returns `doneToday` and
`answeredAt`, held against the account rather than the device. A second tablet
sees it as done.

### B12 — Telling the engine media failed
New `media_load_failed`. `{"segmentId", "channel": "image"|"audio", "reason"}`.
Without it the engine read a child staring at a broken image as a child
disengaging — and could shift modality away from the one channel that worked.

### B13 — Event types for system waits
All of them: `system_busy`, `tap_blocked`, `session_context`,
`baseline_module_start`, `baseline_module_complete`, `baseline_submitted`.
Form factor and reduced motion go on `session_context` as
`{"formFactor": "phone"|"tablet"|"desktop", "reducedMotion": bool}`, sent once
per session.

### B15 — The undefined event types are now defined
Each has a stated trigger and payload in the enum — read them there, they are
the contract:

- `engagement_signal`: the type of last resort. `{"indicator", "value"}`. Use a
  named type where one exists; the engine can reason about those and can only
  count these.
- `modality_switch_outcome`: `{"from", "to", "outcome": "better"|"worse"|"no_change"}`,
  once the child has been in the new modality long enough to tell.
- `break_taken`: `{"trigger"}`, at the moment of acceptance. `break_start` and
  `break_end` carry duration.
- **Ask Nevo now has a session type.** `session_type` takes `ask_nevo`
  alongside `lesson`, `onboarding`, `profiling`, `sso`.
- `BREAK_START`'s trigger stays free text for now — see the open question at
  the end.

### B16 — Quick checks as audio
`ComprehensionCheckpoint` takes `format: "text"|"spoken"` and
`promptAudioUrl`. Decided server-side, so you are not keeping a preferred
modality against a child.

### B17 — Support eases to none
`ScaffoldingLevel` gains `none`. Three values meant the lightest an ordinary
lesson could offer was still something, so a child who no longer needed help
kept being given it.

### B19 — Answering a guided question
`guidedPrompts` sits beside `guidedQuestions` on the adjustment: each prompt
has an `id`, a `prompt` and optional `options`. Answer via
`POST /api/intelligence/guided-questions/answer` with `promptId`, and either
the `option` picked or `responseLength`, plus
`outcome: "moved_on"|"asked_again"|"abandoned"`.

**The child's own words are deliberately not accepted.** A guided question is
a teaching device, not an assessment; what is worth recording is whether the
dialogue moved them on.

### B20 — Events for hints, step-up and guided questions
`hint_offered`, `hint_used`, `step_up_offered`, `step_up_accepted`,
`step_up_declined`, `guided_question_shown`, `guided_question_answered`. You
were right that the calculation solver's hint has been live and reporting
nothing — every piece of evidence about whether hints help was thrown away.

### B28 — A richer review outcome
`RecordReviewRequest` takes `outcome`: `first_time`, `after_hint`,
`second_attempt`, `not_recalled`. The server decides what counts as recall —
only `first_time` lengthens the interval, because a child who needed a hint
needs to see it again sooner, not later. `recallSuccessful` still accepted so
nothing in flight breaks; ignored when `outcome` is sent, and the response
echoes the outcome back.

On the reply being "typed as unknown" — it is not, and was not.
`POST /api/scheduler/record-review` declares `RecordReviewResponse`, whose
`schedule.nextReviewDue` is a typed datetime. Check your generated client.

### B29 — A short progress note
`note` on the progress response, beside `reflection`. Written short, not
truncated.

### B31 — The offline package
The spec now declares it: `application/zip`, holding `lesson.json` (the lesson
package) and `manifest.json`. The manifest gains `sizeBytes` — **measured from
the real archive**, not estimated — plus `files` and `includesMedia: false`.

That last one matters for your screen: media is referenced by URL and not
bundled, so a lesson cached this way is text-only offline. Better said than
discovered.

### B34 — Notifications for a child
Four, and deliberately few: `lesson_assigned`, `review_due`,
`teacher_replied`, `sign_in_changed`. **None about performance** — a child is
told something is waiting or ready for them, never that they are behind and
never anything measured against another child.

`sign_in_changed` is the one you did not ask for and will want: a child whose
PIN was reset meets a PIN that no longer works with no idea why.

**Second empty mechanism found here.** `NOTIFICATION_CATEGORY_BY_TYPE` was an
empty dict, so `notification_category()` returned `None` for every type in the
product and no switch on the settings screen could mute anything at all. Now
populated.

The four have no producer yet — they are declared so you can build the bell,
and each is listed in a test as awaiting a trigger so it cannot be forgotten.

### B35 — Where the child's chosen name lives
`preferredName` on both `PATCH /api/v1/users/me` and `GET`. Its own column, not
`firstName`: the roster name is the school's record of a child and a nickname
is not a correction to it. `displayName` stays read-only and now returns the
chosen name where one is set.

**And yes, the tones carried over.** The legacy `/api/settings/me` route wrote
the same `avatar_tone` column all along, so nothing was lost and there is
nothing to migrate. (Docstring fixed too.)

---

## Answered, no code needed (9)

### B1 — School SSO
Off the board, and I cannot give you a date. When it returns, the provider will
come back on the school-code lookup as a new field on `SchoolCodeResponse` —
not on the auth method, which only says *how* a school signs in, not *who*
with. Nothing creates a school SSO connection today, so the PIN fallback you
are seeing is the correct and only path. Build for PIN.

### B2 — The school entry link
**Delete it from your list.** `accountReady` meant "this child has a PIN and
can sign in normally" — but it does not matter, because that endpoint never
resolved for anybody. It refuses any grant that does not name a child, and
nothing in the codebase ever wrote one: production held four grants, none
naming a student, so every token returned `entry_link_invalid`.

Per SCRUM-208 there is no link now. The child types two fields:

```
POST /api/v1/student-entry/lookup
{"schoolCode": "NP4K", "admissionNumber": "ADM001"}
→ {"firstName", "className", "consentState": "given"|"pending",
   "age", "accountReady", "ageCheckPending"}
```

`POST /student-entry/{token}/pin` has no caller because it should have none.
I would rather delete both than leave routes that cannot answer.

### B7 — A withdrawn child at the door
**Confirmed in the code**, not yet seen end to end. `account_paused` is a
`401`, raised when the credential is right but the account is not open. If you
want it demonstrated against a real paused account, say so and I will set one
up on the temporary host for you to hit.

### B14 — The touch stream
**The Touch Signal Contract is right: raw touch stays on the device.**

Reason: tap coordinates and dwell per element are a behavioural record of a
child far finer than anything else we keep, and we would be storing it for
every child continuously. What the engine needs from touch is already
derivable — `time_on_segment`, `replay`, `scroll`, and now `tap_blocked` and
`system_busy` for the two cases that were being misread as idleness.

So: reduce on the device, send the derived events. If the architecture
document says otherwise, the document is the thing to change, and I will raise
that rather than leave you building to two contradictory specs.

### B22 — Can a child read their own accommodations?
**Yes.** `GET /api/intelligence/accommodations/{student_id}` already allows it:
the guard only refuses a student reading *another* student. Your own token on
your own id works today. Asked 15 September, answered now — sorry that took a
fortnight.

### B23 — Where attention chunks split
**The rule, not boundaries:** split on sentence, maximum three parts, and never
mid-sentence. Design's "about 130 words" is a description of the example, not a
limit. Sending boundaries would mean re-deriving them server-side on every
depth variant for no gain, since the device already has the text.

If design wants a word cap enforced, that is a different decision and needs
them, not me.

### B30 — A session narrative written for a child
There is not one, and I would not build one until counsel clears the screen —
it is under hold, so anything I wrote now might be built against a frame that
changes. When it clears, this is a real ticket: a narrative naming a child and
mentioning modality is written for a teacher and should not be shown to the
child as-is.

### B33 — When the Ask Nevo allowance runs out
Today it genuinely does look like a connection failure, which is a fault worth
fixing rather than documenting. It will return **429** with
`code: "ask_nevo_allowance_spent"` and the time the allowance resets, so your
screen can say when rather than just no. Small, and mine — this week.

### B36 — Reporting a crash
**Build the endpoint; do not reword the screens.** "We're on it" should be true.
`POST /api/v1/client-errors` taking a message, a stack, the route and a build
identifier — and no child's content. Mine, this week.

---

## Mine to build (8)

Named so you can plan around them. None need anything from you.

| Ask | What it needs |
|---|---|
| **B8** (high) | Serve baseline knowledge questions **for the subject the child picked** — they are a hard-coded list ignoring the choice, and saved as the child's real knowledge measure. The warm-up half is done (below). |
| **B9** (high) | A raw-trial ingest endpoint, so the device stops reducing the baseline. SCRUM-175. |
| **B18** | Nothing emits `offer_hint` or `show_socratic_panel`, so a struggling child gets neither. |
| **B21** | `numerical` needs an engine or content payload to act on, or staff are being told something untrue. |
| **B24** | `GET /api/session/state/:student_id`, and `engineConfig` typed. |
| **B25** | SCRUM-177, the calculation as data — including the missing `conceptId` on the segment and on `CalculationVariant`, and a description for `Manipulative.labels`. |
| **B26** | `masteredConcepts`, `revisitConcepts`, `resultNote` from the check-in. Mastery cannot be worked out on the client. |
| **B27** | `ScaffoldAttemptRequest` takes the child's pick and marks it server-side, like the attempts endpoint. |

### Part of B8 is already done

The warm-up no longer ships its own answer key. `answer` is **gone** from the
prompt response, and the child's pick goes to:

```
POST /api/baseline/recalibrate-prompt/{studentId}/response
{"itemId": "...", "value": "..."}
→ {"correct", "dimension", "doneToday", "answeredAt"}
```

Marked on the server against the key, which never leaves it. Answering twice
in a day is accepted and does not overwrite the first answer — a second tablet
offering the warm-up again was the bug in B10, and penalising the child for it
would be a worse one.

The remaining half of B8 is the subject-aware knowledge questions.

---

## One thing back to you, and one to design

**You (small):** `BREAK_START`'s trigger is still free text. You send
`affect_offer`. Give me the full set your client can emit and I will close it
to those values — I would rather type it to what you actually send than invent
a list.

**Design (B6, not on your list):** you have closed B6 because admin resets
issue four digits and return `pinLength: 4`. But SCRUM-179 says send the PIN
length with the PIN and migrate anyone on six, and the validator currently
accepts **either** 4 or 6. So `pinLength: 4` is true of resets and not of the
system, and a six-digit child will meet a four-cell screen. That needs settling
before you build against the field.

---

**Migration `20261001_0088`** carries the fourteen new signal types and the
`preferred_name` column. Applied. Full suite green, ruff clean, mypy unchanged
at baseline.
