# Reply to Lydia: twelve items and SCRUM-257

20 October 2026. Ready-to-send engineering reply; deployment must be confirmed separately from the push to main.

Lydia, thanks. I have kept your order of work and the ownership split. SCRUM-257 is now fixed on the backend, and I will start work on AKT immediately.

## SCRUM-257

Confirmed data-processing consent is now required for student signal ingestion, submitted answers, progress writes and Student Ask Nevo. Missing, pending and not-sent consent return `403 consent_required`; explicit withdrawal returns `403 consent_withdrawn`. If consent cannot be checked, the API returns `503 consent_service_unavailable` and does not proceed.

The same shared gate covers lesson entry, baseline/probe/warm-up processing, adaptation, review processing and offline-package delivery. The ZIP route and both lesson-detail reads are now gated too, closing delivery paths that could otherwise bypass lesson entry. Queued post-lesson work rechecks consent before processing stages; it waits rather than updating a profile or generating flags without confirmation, and can resume once consent is confirmed.

The consent-gate read now reports `blocked: true` for every state except confirmed. Sign-in and consent-management access remain available so the school can resolve the issue. This does not require a frontend change to enforce it, and I have not edited frontend code. Learners with pending records will now be blocked intentionally until valid consent is recorded; I have not auto-confirmed any account or fabricated consent records.

This is a backend policy/code change, not a schema migration. The existing migration `0110` for safety and retention has already been applied. The new consent code takes effect when deployed.

The backend changes passed 273 focused tests. Server checks cannot remotely recall a lesson already downloaded onto a tablet; local offline enforcement and browser cleanup remain frontend-owned.

## The twelve items, in your order

1. **Baseline measurement reduction.** The fabricated reading measurement is fixed: the backend does not save 120 WPM as a measured result when no timed-reading evidence exists. An observed timed reading produces a measured rate; otherwise 120 can still be used as an unmeasured delivery fallback. Migration 0104 removed legacy 120 WPM values without measurement provenance. Age/device calibration and oral-reading validation still require real observations, as you described.

2. **Warm-up recalibration.** Yes, this is the same fix identified in the 17 October report. Recalibration updates the dimension actually measured and preserves unrelated baseline values and delivery settings. The separate whole-profile-reset backend defect can come off the list. The frontend still needs to submit the actual task results; a completion receipt alone cannot recalibrate anything.

3. **Adaptive knowledge probe.** No further change to your accepted no-bank ruling. One available subject completes module 4. Where no eligible bank exists, placement stays explicitly unestablished with a conservative prior; the probe reopens when a bank becomes available. The earlier onboarding modules remain credited. This does not waive confirmed processing consent.

4. **Bayesian knowledge tracing.** BKT remains the live local mastery method, driven by server-marked evidence. Its parameters are provisional defaults, not empirically tuned claims. Evaluation against real learning data remains outstanding.

5. **AKT integration.** I will start immediately with the pinned pyKT reproducibility spike and the authorised vocabulary preparation, then build the private service, outbox and shadow wiring. This is a genuine attention-based model integration, not a rename of BKT. BKT will stay authoritative during shadow mode, and unavailable AKT predictions must fall back safely rather than block learning. Before shadow begins I will preregister the eligible sample count, margin over BKT, subgroup/calibration checks and a decision deadline, so it cannot run indefinitely without a decision. My initial proposed evaluation gate is at least 1,000 eligible held-out sequences from at least 100 learners, at least 5% relative log-loss improvement over BKT with learner-level uncertainty checks, and no material calibration/subgroup regression. At a six-week decision deadline, insufficient evidence means no promotion and BKT remains authoritative. These are proposed engineering acceptance criteria, not a claim of validated performance. Machine unlearning is no longer a blocker under your ruling. Subject mastery versus reading remains a disclosed heuristic today; stock AKT will not make that separation real by itself, so it needs deliberate modelling and evaluation.

6. **Curriculum prerequisites and concept mapping.** Backend tooling and routing safeguards remain in place. Approved prerequisite links and missing comprehension checks still need the subject owner you will appoint. Until then, I will not describe teacher-assignment routing as fully autonomous adaptive teaching.

7. **Progressive scaffold fading.** Backend support changes are implemented. The browser demonstration that support rises and withdraws remains with Olayinka and stays first in the demo set. Hinted or repeated submissions do not become independent mastery evidence.

8. **Pacing that changes delivery.** The backend controls are available. Frontend consumption and preservation of annotation anchors online/offline remain with Olayinka; authoring missing checks stays with item 6.

9. **Simplify and Expand fidelity.** Source safeguards and teacher approval remain required; automatic checks do not prove semantic equivalence. The lesson-wide sign-off/editing branch remains separate and will not merge before the demo. The new safety policy also withholds historical AI additions without a current safety review from new student delivery; demo content must pass the checks as well as have the teacher's approval.

10. **Calculation marking.** Server marking and attempt persistence are implemented; calculations use deterministic interactive scaffolds, not generated pictures. Submitted calculation answers are supported and stored by the backend contract, so the legal wording must not make an absolute claim that calculation entries never reach the server. The step-by-step browser demonstration remains with Olayinka.

11. **Evidence-based spaced repetition.** Yes, the circular dependency is broken. Ordinary server-marked lesson evidence can create the first concept-review schedule without a prior review session or existing schedule. Later review evidence updates it idempotently, including bulk/offline ordering. Concepts still need valid authored checks and concept mappings; scheduling cannot invent missing evidence.

12. **Learner-safe intelligence responses.** Internal cognitive estimates remain separate from the functional feedback and delivery controls needed by the player. Olayinka's nullable-field verification remains necessary: withheld values must not become zero or invented client estimates. Authorised functional school insights and client delivery settings exist, so the documents should not promise that every derived output is absent from every school/student API response.

## Signal wording, retention and crash reporting

The detailed backend corrections are in the signal-path reply already supplied. Inference is server-side; accepted learning events and submitted answers are persisted, not purged when a session ends. The 180-day post-purpose purge now includes signal events, profile history and other covered learner records, with managed-file deletion and retry receipts. Migration 0110 is applied; the verification query found no overdue learners. Backups, infrastructure logs, processor copies and downloaded files still need their own verified retention arrangements.

The crash-report endpoint's application logger no longer logs browser message text, raw stacks/routes or the signed-in account ID. It keeps limited incident metadata and fingerprints. This does not retrospectively erase older logs or certify external instrumentation. Local onboarding-coordinate cleanup and the browser's consent failure default remain frontend-owned checks; the server now refuses processing independently.

Finally, I would keep the earlier wording corrections: no blanket "no third party receives anything" claim while contracted hosting/storage and AI processors are used, and no "the device computes no score" statement without reconciling the reported local answer marking. I have not edited or certified the seven legal documents themselves.
