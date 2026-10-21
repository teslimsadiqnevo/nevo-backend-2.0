# Lesson-player backend repair: team handoff

## Release boundary

Backend only. The new contracts require deployment of the pushed main commit through the separate Render account. Existing production lesson data was repaired separately, without replacing lesson/segment IDs or editing the frontend. Production `alembic upgrade head` is run as part of this work; no new database migration is needed because the additional state uses existing JSONB columns.

## 1. Questions: SCRUM-264

The initial audit found 22 single-answer questions incorrectly labelled multiple_choice across two lessons: 14 checkpoints and eight assessment items. Osmosis accounted for five checkpoints and four assessment items. These are now single_choice, including on reads of older payloads and at parse time. A genuine multi-answer key remains multiple_choice.

Uploads now fail when a question has an unsupported type, missing prompt/key, unusable choice key or malformed question-list structure. Such errors are not allowed to become a deterministic fallback that silently loses questions. Model-supplied concept IDs are still discarded and bound by the database.

Stored-contract reprocessing normalised 313 checkpoint sections and assessments in 16 lessons, across 21 lessons total; those larger figures include option-order/default metadata normalisation, not 21 lessons with the reported type defect. This was targeted reprocessing, not a destructive AI regeneration of teacher-edited lessons. The post-repair audit found zero remaining instances of the reported scalar-key/multiple_choice defect.

## 2. Progress and adaptation: SCRUM-269

Progress and adaptation handlers were exercised using Nura's actual stored Osmosis sitting and profile in rollback-only transactions. Both passed, including response-model validation. The adaptation replay temporarily reopened the ended sitting inside the rolled-back transaction so its in-lesson path could be exercised. An ended sitting correctly returns lesson_session_required when not reopened.

Progress now validates assignment ownership and lesson membership before storing a supplied assignment ID, rather than relying on a foreign-key failure. A further rollback-only replay used Osmosis's real questions: three misses opened socratic_panel, all nine correct answers were marked correctly, and completion returned landed. These calls also exercised the local mastery/review write paths without retaining simulated answers. HTTP/SQL regression tests cover the player flow. However, the four original incidents have not been causally explained: no original payloads or private Render tracebacks were available. Do not mark those incidents definitively resolved solely because the current replay passes. A fresh production run remains required; this is not being described as a transient fault.

## 3. Osmosis scientific corrections

Two expanded passages were corrected: the membrane explanation had described holes as large enough to stop larger particles, and the summary had reversed soil/cell-sap concentration while claiming inward movement. Both corrected passages passed the real content-safety check. Their previous teacher approvals were cleared and reviewStatus is pending: edited prose cannot inherit a sign-off on different prose. Original text and the six approved simplified versions were not replaced. Rewrite instructions now explicitly prohibit reversing directions, comparisons, causes, negations and inequalities; this is not a claim that automated factual checking is infallible.

## 4. Pictures: SCRUM-270

The root cause was that VisualVariant discarded safetyPolicyVersion during validation/storage. That field is now retained.

The initial count was 20 visual payloads without a current stamp. Inspection distinguished 18 real images from two historical diagram proposals with no image URL. All 18 real images, including Osmosis's four, were downloaded from the configured storage host, decoded and passed through the real image safety check before stamping. The two proposals remain unavailable; no imaginary image was stamped.

Osmosis's actual availability after repair:

| Section | Cleared content present |
| --- | --- |
| 1 | Text, picture |
| 2 | Text, audio, picture |
| 3 | Text, picture |
| 4 | Text, picture, activity |
| 5 | Text |
| 6 | Text, audio |

YarnGPT quota recovery and generating the four missing recordings remain outside this repair, as requested.

## 5. Format control and persistence: SCRUM-272

Lesson segment responses now carry availableFormats and recommendedFormat. The canonical format values remain text, audio, visual and interactive; UI labels can say Picture and Activity. Availability is derived from actual payloads, not just the declared modality list. A picture must have a current safety stamp and URL; audio must have a recording URL. Calculation scaffolds are interactive, not generated pictures. Existing authored opening order is preserved among available formats.

recommendedFormat is null where no recommendation exists. Adaptation responses carry the same availability/recommendation fields per segment. The old separate modalitySuggestion field is deprecated and returned null; it is not a second instruction surface.

Write explicit choices with:

`PUT /api/v1/lessons/{lessonId}/sessions/{sessionId}/segments/{segmentId}/preferences`

```json
{"modality":"audio","depth":"simplified","slower":true}
```

Writes are partial; omitted fields are preserved and null clears that particular override. Unsupported/unavailable format returns 409 format_unavailable; an uncleared depth returns 409 depth_unavailable. Only the owning student, with confirmed consent and access to the lesson, can write. Closed sessions are refused. The server supplies updatedAt.

The session response's deliveryState.segmentChoices is keyed by database segment UUID. It survives session resume/reload and does not apply to other segments. Lesson reads also expose deliveryPreference and the chosen primaryModality. Adaptation respects the explicit format, returns chosenDepth/slower, and withholds conflicting Simplify/Expand/Slower actions. Recommendations may remain visible, but do not replace the choice. No preference is written as a permanent learner-profile label.

The engine previously returned a segment modality and a separate suggestion; it did not autonomously mutate the stored lesson into another format. The client could apply those instructions. The new server contract now protects explicit choices in those responses too.

A format choice through this write produces modality_manual_switch with source=student_control. Accepted engine offers retain modality_suggestion_accepted. The frontend should not additionally send the same manual event for a successful preferences write. A first manual event may have fromModality=null when no previous explicit choice exists; the server does not invent what was previously rendered.

## 6. Numbered lists: SCRUM-267

The old sentence regex treated any period followed by whitespace as a boundary, including 1. and 5. The reading chunker, source-claim splitter and activity recovery now distinguish numbered markers from sentence endings. The word-budget fallback also avoids stranding a marker at the end of a chunk.

Stored reading boundaries were rebuilt for 54 sections from the unchanged source bodies. Unchanged text anchors retain deterministic IDs. Stray number-only sourceClaims were rebuilt. The production audit found no stored activity steps consisting solely of a numbered marker. Source text, questions and teacher-authored instructions were not regenerated.

## 7. Answer-position bias: SCRUM-265

Before repair, the entire live probe bank consisted of four Mathematics items, all with the correct answer in stored position one. Their lesson and creation records trace to the parser's copied checkpoints, not a separate probe seed path. The pipeline preserved provider option order; the observed stored bias is established, but a universal generator rule is not asserted.

Options are now presented in stable, answer-independent hashed order: per student/item for probes, per student/item/day for served warm-ups, and per question for checkpoints/assessments. Values and answer keys remain unchanged, so saved answers still resolve. Repeated reads do not randomly rearrange an active question.

The post-repair bank has three active Mathematics items, one retired Mathematics item and five active Biology items. Across stored multiple-choice checkpoint questions after normalisation, correct positions 1–4 were 81/109/90/55; for assessment questions, 16/15/21/12. No claim is made that the pre-repair checkpoint/assessment position totals were measured: that full histogram was collected after repair. Onboarding device activities are not ordinary choice-bank questions, so their task stimuli were not arbitrarily reordered.

## 8. Probe relevance and continuation: SCRUM-266

Osmosis had segment concept IDs but no lesson subject; the school had no Biology bank. The original onboarding selection picked the first available subject, Mathematics, and was not lesson-concept-scoped. This was both a missing content mapping and a selection-contract limitation.

The explicitly reported Osmosis lesson is now mapped to canonical Biology, with its concepts and five standalone checkpoint-derived bank items linked accordingly. Biology is linked to the reported SS 1 Science class, not silently added to every demo class. One Mathematics item referring to an absent worked example was retired, and future bank creation/serving excludes the supported context-reference patterns. This filter is conservative, not a proof that every possible contextual phrase can be detected automatically.

`GET /api/v1/students/me/onboarding?lessonId={id}` returns a preferred matching probeSubjectId, lessonProbeStatus (available/unavailable/subject_unmapped) and returnTo. It persists the intended lesson server-side. Opening an assigned lesson while onboarding is incomplete also remembers that lesson. Readiness then returns that destination even without the query parameter.

Probe next accepts optional lessonId; ProbeAnswer accepts lessonId too. With it, the backend validates the lesson/subject and limits items to the lesson's concepts. A mismatched subject is refused with 409 probe_subject_mismatch, not replaced with another subject's questions. ProbeFinished returns navigatesTo for the remembered lesson. The frontend still has to follow that destination; the backend cannot navigate a browser. The global module-four rule remains one available subject, not every subject.

## 9. Accepted no-bank rule

The relevant changes were brought across without merging the held lesson-review redesign. No-bank placements are explicitly unestablished/no_question_bank, without a fabricated measured placement. Conservative mastery seeding has provenance unestablished_conservative. When an eligible bank appears, only domain_probe reopens; the earlier three completed modules remain credited. A completed probe records established or unestablished/no_scored_answers as appropriate. HTTP regression coverage verifies no-bank entry, reopening and return-to-lesson.

## 10. Safety-stop copy: SCRUM-259

The 403 content_safety_blocked message is now exactly: “Nevo can’t help with this one. Please talk to a trusted adult or your teacher.” The frontend must retain the distinct safety-stop presentation rather than its ordinary retry screen.

## 11. Word Conflict

The backend accepts interference_control, with congruent/incongruent conditions. Reduction derives within-child accuracy cost and relative latency cost against congruent trials, not an absolute speed score. Anticipations are excluded; the slow tail is capped; inadequate trials or congruent performance return unestablished without a fabricated value. Only aggregates are persisted. The result is not returned as a visible learner score.

The provisional, versioned binary-task policy is: at least 12 valid trials per condition; 200 ms anticipation floor; 5,000 ms latency cap; congruent accuracy must exceed 0.75; at least three correct latency trials per condition. Joint accuracy cost >=0.15 and relative latency cost >=0.20 select shorter blocks and reduced competing material. These are engineering defaults, not population-calibrated scientific claims, and need review before the extra SS task time is approved. No new compulsory onboarding module was enabled.

The production aggregate audit found zero usable flanker contrasts, zero Word Conflict contrasts and zero paired children. Whether the tasks track together is therefore unestablished; neither correlation nor non-redundancy has been invented. That empirical question requires paired observations and product/research review.

## 12. Verification and remaining boundaries

374 focused tests passed, covering question storage and marking, adaptation, scaffold behaviour, choice persistence and engine precedence, no-bank reopening, baseline reduction, consent and safeguarding. Production migration upgrade completed successfully at the existing 20261020_0111 head. The Git commit is reported alongside this handoff.

Remaining: deploy the new main commit through the separate Render account and re-run the actual browser demo; two corrected expanded passages need renewed teacher approval; the four original 500 incidents remain causally unconfirmed despite successful rollback replays; the flanker/Word Conflict overlap question lacks paired data and the provisional thresholds need review. Frontend wiring and media quota recovery are not presented as completed backend work.
