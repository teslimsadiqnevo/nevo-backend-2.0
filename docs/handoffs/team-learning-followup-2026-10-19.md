# Team reply: learning engine follow-up

19 October 2026

1. For Wednesday's demo, the order is calculation marking/step delivery, support
   rising and fading, approved Simplify/Expand, then onboarding/access and the
   new response contracts. The backend fixes for those first three are shipped;
   the actual demo lesson needs approved content and a browser run. We are not
   holding the demo for AKT or claiming the whole learning-science document is
   validated. The complete current Lydia list has not been rechecked here.

2. No-question-bank behaviour is explicit: `domain_probe` returns
   `completed: true, status: "unavailable"`, not `not_required`. The other three
   modules remain required. Once those are complete, the missing bank does not
   cause an onboarding 409 on lesson entry. No knowledge placement is invented.
   Normal consent/access/assignment gates still apply.

3. Run one available subject from the child's enrolled classes. The onboarding
   read supplies `probeSubjectId` and `probePolicy: "one_available_subject"`.
   One completed subject is enough initially, not a placement in all subjects.
   An empty bank in one subject does not waive another available subject.

4. Existing children with the first three modules credited only need module 4
   when questions exist. Migration 0105 credits genuine earlier baseline/lesson
   evidence; it does not exempt every old account merely because it is old.
   The E2E student is already complete: live onboarding returned 200 with
   `complete: true, nextModule: null`, and its dashboard returned 200.

5. Student-contract heads-up: this has already landed, so it should have been
   flagged earlier. `baselineProfile` is empty; internal numerical mastery,
   reading and scheduling estimates plus probe `entryPoint` are nullable and
   withheld. Player settings and functional feedback remain. Reading groups and
   warm-up measurement receipts are documented in the implementation handoff.
   Please do not convert nulls to scores. No frontend changes were made here.

6. Calculations do not generate pictures. A valid one advertises interactive
   only, with the scaffold inside the player. Invalid/missing calculation data
   falls back to source text and available audio with review required. A renderer
   failure on the device should use the source body and report the failure.
   Choice `acceptedAnswers` contains only forms of the right answer; `targets`
   contains all offered options. Delivery and marking filter distractor aliases.

7. Affective: understood and accepted. Raw touch remains device-only and anxiety
   stays retired for v1. Productive-confusion grace/action wiring remains a frontend
   verification item; I have not marked that browser check passed.

8. Use `https://api.nevolearning.com` as the canonical API address. I cannot account
   for the old suspended Render hostname from this checkout. Live health now says
   expected 0108 / applied 0108 / up to date; 0105 has run. The old 0104-final note
   is obsolete. Configured media status does not prove provider recovery.

9. SCRUM-252 is implemented and in Testing, not Idea. Own-class teachers can read
   profiles and adaptation history without Learning Support; unrelated teachers
   cannot, and holders have same-school wider access. Home taps must call
   `POST /api/intelligence/flags/{id}/seen`: that is personal read/dismissal only.
   `/acknowledge` is the separate Learning Support action and records the holder's
   identity/time. Use `seenByMe`, `seenAt` and `unseenOnly=true`. Live E2E own-student
   profile/adaptation and unread-flag reads all returned 200. Jira currently shows
   253 Done, 244 Testing, 252 Testing; final acceptance is still yours to exercise.

10. I added nullable `reviewedByName` alongside `reviewedBy` on staff rewrite reads,
    resolved from the school account rather than generated content. It passes the
    local runtime check and needs this follow-up deployed; no migration is required.
    Missing/deleted reviewer names remain null. Students do not receive the name.

The dedicated E2E teacher/student sign-ins were rechecked live and both returned
200. Credentials are supplied separately, not committed to this response.

On the model question: BKT is already running locally. AKT is a proposed separate
Nevo-hosted model using pyKT, first in shadow mode with BKT still authoritative.
It requires eligible data, training and evaluation; it is not an external vendor
API or a prerequisite for the demo's scaffold and adaptation behaviour.
