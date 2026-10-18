# Frontend follow-ups: 18 October 2026

## Rollout

The changes in this handoff require deployment and migration `20261018_0105`.
Render's start script runs `alembic upgrade head` before starting the API.
Local verification is not confirmation of production deployment.

## 1. Onboarding and the knowledge probe

- One available subject from the child's enrolled classes is sufficient for initial onboarding; other subjects do not receive invented placements.
- `GET /api/v1/students/me/onboarding` returns `probePolicy: "one_available_subject"` and a recommended `probeSubjectId` (or null).
- If no enrolled subject has active probe items, the server records `domain_probe_status: "unavailable_at_onboarding"`; the module returns `status: "unavailable"`, `completed: true` for routing, with no measured placement. The other three modules remain required.
- An empty bank for one subject does not waive the probe if another eligible subject has questions.
- The unavailable outcome is durable: adding a bank later does not unexpectedly re-block a child. A later probe can still record a real placement.
- Migration 0105 preserves the first three modules for children with recorded lesson activity or evidence from the former completed-baseline path. It does not infer completion from account age or default engine settings. Children with no completion evidence still need those modules.
- Existing children with the first three modules credited need module 4 only when a bank is available. Resuming an already-finished probe also persists its completion.
- Declined-only probes do not save an unmeasured prior as a subject placement.

## 2. Calculation delivery

- Calculation segments do not enter image generation. Their deterministic scaffold belongs inside the interactive calculation player, not a separate visual modality.
- A valid calculation advertises `interactive` only, including on reads of older stored lessons.
- A missing or invalid calculation retains source-text delivery (and audio where available), with review required rather than an empty lesson.
- A frontend renderer failure is not visible to the server: the client must use the returned source body for its own fallback and report the failure.

## 3. Accepted answers

- Choice-step `acceptedAnswers` is restricted to representations of the correct answer. Distractor IDs are removed from old and newly returned steps and ignored by server answer marking.
- `targets` remains the offered choices, not the accepted-answer list.

## 4. API address

Use `https://api.nevolearning.com` as the canonical integration address, not a Render service hostname. The reason the older `-kn3d` service is suspended has not been established by this work.

## 5. Verified E2E accounts

The existing teacher account signed in and opened its dashboard successfully. The documented PIN on the existing `NV-E2E000` test student was restored, and its live sign-in and dashboard also returned 200. Credentials are supplied separately rather than committed in this handoff. The former `teacher.demo@nevolearning.com` account is not present in the current database.

## 6. SCRUM-252: access and the two seen actions

- A class teacher can read their own pupils' profiles and adaptation history without Learning Support.
- A teacher holding Learning Support can read other pupils in the same school; another ordinary teacher cannot. Administrators still need Learning Support for adaptation history.
- Teacher flag lists are limited to their own pupils unless they hold Learning Support.
- `POST /api/intelligence/flags/{id}/seen` records only the current staff member's personal read; it does not set support acknowledgement.
- Flag reads include `seenByMe` and `seenAt`. Use `GET /api/intelligence/flags?unseenOnly=true` for personal unread Home cards.
- `POST /api/intelligence/flags/{id}/acknowledge` is the separate Learning Support action and requires that grant. It retains the original professional's name and timestamp.
- Migration 0105 converts earlier ordinary-teacher acknowledgements to personal reads where the teacher did not hold Learning Support at the time.
- School-wide accommodation reads remain Learning Support-only; the own-class exception does not open that school-wide surface.

## Verification

- 21 existing disposable-database runtime tests passed.
- 34 existing calculation/adaptation regression checks passed; the existing modality assertion was aligned with interactive-only calculation delivery.
- Targeted HTTP checks passed for own-class access, unrelated-teacher denial, holder-wide access, personal read isolation, restricted support acknowledgement, and no-bank onboarding followed by lesson entry.
- Migration 0105 upgraded a disposable local database successfully. Ruff and whitespace checks passed.
- Live E2E teacher and student sign-in and dashboard reads returned 200. No production claim is made yet for the new contracts above.
