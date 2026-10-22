# SCRUM-277: authored hint after two question misses

## Delivered contract

The existing `POST /api/intelligence/adapt` response still carries the hint in
`proactiveAdjustment`, with `action: offer_hint`, `hint`, `segmentId` and the
normal decision/disposition fields. No new frontend request or route is required.

Two server-marked misses on the same unresolved question offer that question's authored
hint, independently of the learner's previous sessions, personal baseline, adaptation
confidence threshold, number of aligned categories or adaptation cooldown.
The hint uses a separate deterministic question-support rule, not a relaxation of
the constraints on Simplify/Expand or format changes. Its audit evidence is
`question_support / two_marked_misses`.

The count comes from saved attempts, not client-reported miss counts. Different questions
do not pool misses; declines do not count as misses. A correct answer ends that miss run.
If the question has no nonempty authored hint, no hint is generated or borrowed from a
different question/calculation step in the same section.

Repeated adapt calls retain the same active hint and decision ID rather than making
another offer. A solved question clears active support. An existing Socratic panel is
not replaced by a hint. The age-based productive-confusion grace window for the panel
is unchanged; a hint is available while the child waits for that later support.

The sitting records which questions received a hint. Later attempts on those questions
are saved with at least one hint even when the client omits `hintCount`, so assisted
success cannot be recorded as unaided success and incorrectly drive scaffold withdrawal.
This does not add hints to authored lesson content or persist a new learner label.

## Deployment and verification

Backend only; no database migration is needed. Deploy the new main commit.
The regression tests cover no-history learners, first versus second miss, the existing
adapt response, repeat-call identity, missing authored hints, unrelated step hints,
adaptation cooldown, guided-support grace and server-side hinted marking.

Admin E2E is closed on the supplied evidence: Yinka reports the 12:30 UTC rerun passed
after 864dff0. No additional admin-page fix is claimed or needed from that report.
