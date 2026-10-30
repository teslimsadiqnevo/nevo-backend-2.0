# Application, attention and humans in the loop: two-phase delivery

Source: Lydia's 28 October 2026 engine specification, *Application, attention and the humans in the loop*. This is an implementation plan, not a claim that the described behaviour is live.

## Non-negotiable boundaries

- The server owns check classification, mastery evidence, return scheduling, marking and access control. The player renders approved contracts; it does not infer the child's level.
- Generated questions, inferred levels, guided steps, images and other generated teaching content require the existing teacher sign-off before delivery to a child. A generated answer key is never silently treated as source-authored.
- No model judgment of a child's free-text answer can make a gate pass. Every gating item has a deterministic, reviewed marking key.
- An unknown level, unreadable paper image or missing camera cannot block progress. Unknown evidence stays unestablished.
- Do not report depth labels to children, treat time in app as learning, or claim that a browser can lock a child into the app.

## Batch 1: learning depth and transfer

1. **Check contract and provenance.** Add `masteryLevel` (`knowledge`, `application`, `analysis`) and `masteryLevelAuthoredBy`; only source-explicit labels are person-authored. The parser may propose a level, but the proposal and the whole markable question appear in teacher review. Existing checks without reliable level evidence remain unestablished until reviewed or reprocessed. Check assessment items as well as in-lesson checks. A content-hash change invalidates the relevant sign-off.
2. **Level-specific mastery.** Add a separate student/concept/level estimate and event provenance, rather than relabeling or copying the current concept-wide probability. Migrate without inventing historical level evidence. Server-marked attempts update only the reviewed level tested. Supported passes remain distinct from unaided passes. Keep existing concept-wide API compatibility while exposing per-level status to authorised staff.
3. **Gate at the missed level.** A miss at application re-teaches application, not the definition. A second check in a section gates independently. Available ways in must be the child's currently cleared, approved formats plus the content-free support levers. Preserve the production gate flag; do not enable the gate until the player can serve the ways in and an always-available break.
4. **Level-aware spaced return.** Keep existing stability/retrievability timing. At due time, choose an approved item for the next supported level: knowledge to application, application to analysis, then the highest level supported by that lesson. Never reuse the same question as evidence of transfer; with no approved higher-level item, leave the return pending rather than inventing one. Supported recall returns sooner under existing scheduler semantics.
5. **Generate transfer items.** Generate source-grounded, markable application questions in a genuinely new situation and analysis questions that compare, judge or diagnose. Generate at least two materially different contexts plus an explicit common-principle comparison where the source supports it. Validate non-leakage, distinct options, held keys, safety and curriculum fidelity, then require teacher approval. Track context identity so the scheduler can select the second context and then comparison instead of repeating the first.
6. **Batch 1 verification.** Check parsing/review and invalidation; demonstrate a knowledge pass cannot raise analysis mastery; an application miss re-teaches application; due returns advance context/level without changing review timing; unsupported or unapproved generated content never reaches student reads. Measure cost per check and per generated transfer item before library backfill. No bulk backfill before Lydia approves measured cost and sample quality.

## Batch 2: paper, attention and the adult loop

1. **Paper work.** Add an optional paper-work item, a short-lived upload and a no-camera route. Reject person-containing images before image analysis; do not store them as learner working. Apply image safety review before OCR/vision. Extract steps and match them to teacher-approved expected steps, reporting unreadable/uncertain work as unestablished. Do not let model-only interpretation of handwritten work pass a comprehension gate. Store the minimum marked evidence under the learner retention policy, with an explicit consent/privacy review for image processing.
2. **Focus and timing.** Add paired pause/resume events scoped to session and section with idempotent timestamps. Exclude verified away intervals from response-time and time-on-segment calculations, including across reloads and reconnects. Never infer confusion/frustration from an absence. Expose per-child, near-real-time departure status to authorised class teachers, not to other students. A browser can detect visibility changes but cannot prevent app switching; device locking belongs to school management.
3. **Teacher practicals.** Mark an activity as suitable for a hands-on class practical only when its approved content supports that claim. Return materials/requirements and safety line in the teacher lesson read, with teacher review on generated additions. Do not infer from the mere presence of an activity.
4. **Parent evidence.** Add authorised parent reads for concepts that strengthened, scheduled returns and out-of-school learning events, without hours-as-progress or cognitive score labels. Notify only when a concept returns because it was not retained, subject to consent and notification preferences. Avoid implying a child did not learn from an absence of evidence.
5. **Batch 2 verification.** Measure OCR accuracy on photographs from real school devices and poor light, including failed/person-image cases and no-camera continuation. Check visibility timing across target browsers/devices, network loss and reconnect. Verify class scoping, parent consent and suppression of child-facing attention labels. Price per paper image and compare against a minimum reliability threshold agreed with Lydia before rollout.

## Delivery and migration rules

- Work on `codex/application-attention-engine`; do not deploy partial gate/mastery behaviour.
- Use additive migrations and an explicit backfill plan. Apply a migration to the intended production database at the same deployment boundary as code that requires it, never after code starts reading missing columns.
- Release Batch 1 behind server-controlled activation and verify with pilot lessons before enabling the gate. Batch 2's paper feature needs its own privacy and device acceptance before activation.
- The frontend must receive advance contract notes for check levels, transfer items, paper capture, pause/resume and adult-facing reads. This plan authorises backend work only; frontend changes remain Yinka's lane.

## Current status

- Started: in-lesson check-level fields, parser proposals and review material on this feature branch. Parser-inferred levels require sign-off; the live concept-wide mastery and scheduler remain unchanged.
- Not yet implemented: assessment-level review, level-specific mastery, level-aware gating/scheduling, transfer generation, paper capture/marking, focus pause, practical surfacing and parent evidence.
