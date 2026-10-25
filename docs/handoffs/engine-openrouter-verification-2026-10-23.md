# Current engine edits: verification findings

Checked the uncommitted backend edits against Lydia's SCRUM-281/283/284/285 instructions on 23 October 2026. No frontend changes or test files were written. These findings are not a production certification, and these engine edits have not been pushed by this verification.

## Upload release: passed local HTTP checks

Main commit 8564f5d is pushed. Migration 0114 is applied to the configured shared database. A fresh Seed Germination upload became reviewable in 129.2 seconds before optional media completed. On recheck, teacher login, upload polling, lesson detail and media status all returned 200; reviewReady remained true despite explicit optional-provider failures. Cached-image approval/student visibility, source-change refusal, retry and lease recovery were verified earlier. The synthetic verification assignment was cancelled through HTTP (204).

Fresh image generation and successful narration were not verified: the image key was unavailable locally and YarnGPT returned quota failures. These are not reported as recovered.

## Engine release: blocked

1. SCRUM-283 evaluation is a placeholder, not a semantic marker. Direct execution with option='nonsense' and outcome='moved_on' returned correct=true. An empty submission also returned correct=true because outcome defaults to moved_on. The request carries response length, not the child's free-text answer; it cannot determine understanding from that. Do not publish this as evaluated mastery.
2. First-miss support can crash. A text-only explanation with no simplified variant raises NameError because ContentSegmentType is not imported in adaptation.py. Ruff also finds undefined create_engine in two API paths.
3. Scaffold recording accesses payload.session_id, but ScaffoldAttemptRequest has no such field. Valid scaffold requests can therefore fail before recording.
4. The proposed support ladder has no progression state. For an explanation with Simplify and guided questions, one, two and ten misses all return simplify. The slower branch likewise precedes the panel indefinitely on explanation sections.
5. No new server-side concept-pass gate was added to progress writes. Existing prerequisite checks are not proof that the current question was passed. SCRUM-281's prohibition on advancing without understanding is not implemented by returning a proactive action alone.
6. Global adaptation confidence, signal confirmation, dwell time, cooldown and shift-cap constants were relaxed. This is broader than changing the first-miss response and conflicts with the instruction to keep the withdrawal policy unchanged. The scaffold three-success constant itself remains three.
7. Supported correct scaffold answers are excluded from independent success, but the existing engine then classifies them as STRUGGLED and increases support. A supported pass needs its own non-independent-success treatment rather than being treated as a wrong answer.
8. Breaks still trigger from elapsed continuous time alone. Escalation counts BREAK_SUGGESTED as well as BREAK_START, so repeated suggestions can count as completed breaks. STOP_FOR_DAY is a recommendation enum, not a demonstrated persisted stop/resume policy. These changes do not yet satisfy SCRUM-284.
9. Guided/scaffold signal writes construct new database engines instead of using the application session factory, and the engine name is undefined. They also need proper school/student/session ownership validation before recording.

The lint check reported 30 errors across the changed engine files, including formatting issues and the undefined names above. It was diagnostic only; no automatic rewrite of the other tool's changes was performed.

## Five quarantined imports: read-only database confirmation

All five have a Page 1 fallback text question with no answer key and no options. Strict normalization rejects each with 'prompt and answer required'. They cannot become compulsory pass gates as stored.

- 166a173f-ffe3-476a-abc0-8eb95695d0e6: CS2800 Chapter3.
- 5c6d3998-3c38-4eb6-84e9-894dd5bb5309: CSC324 Formal Specification Z Exam Guide.
- 92e17dd3-8d50-42cf-92bd-b609e8bfd77a: CSC324 Formal Specification Z Exam Guide.
- ce9e0224-4f3d-4ced-bc5f-60f8681cd4fc: CSC324 Formal Specification Z Exam Guide.
- f51222e2-e6c9-4269-aaee-3f1f8d2c3cce: CSC324 Formal Specification Z Exam Guide.

Keep these imports quarantined pending replacement with valid authored questions or a decision to drop them. Their absence of a key is not something to repair by inventing a correct answer.

## Evaluation proposal for Lydia

Use teacher-approved, question-specific structured checks with deterministic marking for any decision that unlocks progress. The Socratic panel may guide, but response length, client navigation and unapproved model judgements must not certify understanding. If free-text semantic evaluation is wanted, first agree the approved rubric, uncertainty/refusal behaviour, teacher review and privacy contract; it is not present in this patch. Re-teaching successes should be stored as supported, while the three unaided-success fading rule remains unchanged.
