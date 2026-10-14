# Remaining Jira tickets: first implementation batch

## SCRUM-101

The parse prompt now requests optional natural modules, with titles, segment keys, recaps and previews. The parser validates that suggested modules cover the segments without overlaps. No natural grouping means no modules. Persisted modules have nullable `lesson_segments.module_id` membership. Lesson detail nests the actual segment documents under each module while retaining the existing flat segment list and references. Staged confirmation accepts segment-only lessons via `lessons[].segmentIds`; it no longer invents a module every five segments.

## SCRUM-213

The baseline accepts reach-and-tap samples, discards the first two practice samples, computes the exact median, stores scored-sample and miss counts, and corrects observed trial latency before reduction. Baselines are retained separately for tablet_touch, desktop_cursor, and phone_touch. mobile_touch is a compatibility alias for phone_touch. No timing from another device is borrowed. No baseline means uncorrected_no_baseline, with no invented motor value. Short runs are accepted, with their actual sample count.

## SCRUM-219 and SCRUM-224

Generated lesson text is marked Nevo-authored; source fallback retains person-authored defaults. Checkpoint questions and options, key terms, callouts, captions and transcripts already expose their provenance in typed schemas. Assignment notes explicitly expose person authorship. Calculation notation explicitly disallows language rewriting. time_on_segment records depthShown, and profile inference reads it when interpreting the work.

The 18 September history does not show a removal of key points. Migration 20260918_0062 says the field already existed but the prompt had not requested it, and adds the generation instruction. No backend evidence establishes a freeze removing that field. The new prompt also explicitly requests key terms and relevant equation callouts; empty fields are legitimate where the source has none.

## SCRUM-134

The prompt requires sequenced activities with materials and an observable outcome. A question with options or an answer key is not converted to a fake activity. Missing actual steps or outcome makes the interactive delivery unavailable and puts the segment into review. Questions remain comprehension checkpoints.

## SCRUM-123

Senior/standard access levels exist. School creation creates the senior account; invitations create standard accounts. School updates and promotion already enforce senior access. A dedicated GET /api/v1/settings/school now enforces the same gate for the Settings read. GET /api/v1/school remains the shared school metadata read used outside Settings. Personal preferences stay available to their account owner. The frontend Settings screen should use the dedicated Settings read. Demotion with last-senior protection was shipped in 8251a45.

## SCRUM-206 and SCRUM-138

All five phases are emitted by the existing pipeline: receiving_file, reading_document, finding_sections, preparing_adaptations, ready_to_assign. SCRUM-206 explicitly supersedes SCRUM-138's three-stage remedy; the latter should be closed as superseded rather than reimplemented.

## SCRUM-226

User preferences are stored on the account, merged through the settings writes, and included in password, PIN, and recovery session responses. Accessibility keys are accessibility.reducedMotion, accessibility.highContrast, accessibility.textSize, with break preferences retained in the same account bag. Existing browser-only preferences cannot be imported by the backend; users must save them once to the account, after which they follow sign-in across devices. No frontend files were changed.

## SCRUM-242

Date differences remain roster notes and never block entry or learning. The school date stays operative; the school read never exposes the parent's date. Parent resubmission cannot clear an existing difference. Only the school's roster correction calls reconciliation to clear it. The single AgeCheck row is the school note; it does not send email or repeat notifications. There is no staff adjudication endpoint.

Migrations 20261014_0100 and 20261014_0101 were applied to the configured Supabase database. Frontend rendering/interaction remains owned by the frontend team; the backend changes and contracts above are the scope verified here.
