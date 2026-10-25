# Respiration upload parsing failure

The first upload, `a0605230-b928-423d-b87e-b37222300441`, failed after about
74 seconds with `Unsupported question type in 9: selection`. This is a real
question-schema failure, not a network upload timeout. Its job records failed
status and a teacher-facing reason.

The second attempt, `e5d0fae7-c6fa-437b-acd5-686e5246bbd3`, passed section
parsing and was still preparing adaptations at the database check at 06:54 UTC.
The initial upload response was quick; subsequent preparation includes model
rewrites, safety review and media generation. This release does not claim that
external generation is instant or that the second attempt has completed.

## Correction

- Normalize documented snake-case question fields and a `choices` array before
  strict type classification; preserve matching option values and answer keys.
- Explicitly require the supported question types in each parse request.
- An unclassifiable model question gets one bounded, source-grounded correction
  attempt before media generation. It must retain every original question prompt
  and count, and still pass strict marking validation. Persistent invalid output
  fails the upload instead of publishing missing or fabricated questions.
- Preserve provider truncation diagnostics when JSON is incomplete.
- Repeated same-owner, same-school, same-source staged submissions reuse a recent
  processing job rather than launch another parse/media job. An in-flight reuse
  is not counted as a completed-media cache hit. This does not claim distributed
  single-flight protection for perfectly simultaneous submissions.

No frontend changes or database migration. Deploy the pushed backend commit
before relying on the new handling. Existing running tasks use the code loaded
when they started; deployment can interrupt them, so retry a failed/interrupted
job once the deployment is healthy.

## Local HTTP reproduction: probe insertion rollback

A real multipart upload to the local backend, job
`52bc4da9-0184-49d2-a644-d1518329bf41`, passed parsing and reached storage,
then failed at about 113 seconds with incident `1f2ef7484dc9`.
`probe_items.correct_option` is limited to 80 characters. The repository was
trying to insert a free-text comprehension question with no options and an
86-character prose answer into that choice-only bank, rolling back lesson storage.

The repository now copies only eligible, standalone single-choice checks with
at least two options and a matching answer. Their probe-only option values are
short keys, with the correct key mapped to the original option value. Lesson
questions, labels and long prose answers are preserved unchanged.

The error classifier also matched `429` inside a UUID in the SQL parameters and
misreported this storage failure as a busy service. Numeric status matching now
requires a complete token; overlong stored values are classified as save failures.

No new test files were written for these corrections, as requested. Verification
uses the running HTTP server and real source PDF. The local environment has no
OpenAI image key, so it cannot certify image generation.

The fresh multipart run after this correction, job
`eac0f450-65fc-4875-b25e-1e9209ee119e`, reached `ready_to_assign` in 164.9 seconds.
Lesson `c2a04fc5-6d06-4124-bfa6-8f30af7f0eff` was persisted with 11 sections,
14 checkpoints (single-choice and text) and four assessment questions.
Both `/api/content/lessons/{id}` and `/api/v1/lessons/{id}` returned HTTP 200.
The local server used the configured shared database and the existing spare
teacher account, so this verification lesson is visible in that test school's
library. It is not automatically approved or assigned.

Media recovery is not claimed: local narration calls returned HTTP 402 and no
local OpenAI image key is configured. The local server remains available at
http://127.0.0.1:8000 with the corrected repository code. No migration is needed.

## Transport in plants: production verification

Fresh production upload `c92d337f-cc79-4b1e-8dc7-d32ac26b4339` returned HTTP 201
in 1.42 seconds, then failed after 114.5 seconds with incident `2766d9a7d333`.
The whole-lesson correction changed the question set, and preservation validation
correctly rejected it. This was not a successful upload.

Correction now operates on invalid question fields only, using the dedicated
`content_question_repair.default` prompt. Each invalid question receives a
server-created repair ID. Every repair must be present exactly once and pass
strict marking validation. The server copies back only marking/rendering fields;
it keeps original IDs, prompts, hints, section structure and all other questions.
Fallback prose cannot be accepted as a repaired question. A real Claude call
successfully corrected a malformed selection question through this path.

Migration `20261023_0113` installs the prompt and has been applied to the shared
production database. The updated code requires deployment before the new
production retry. No test files were added or changed.

After deployment, fresh production job `0762adca-d015-4792-8c25-be1df34be08b`
reached ready in 456.7 seconds (7 minutes 37 seconds). Saved lesson:
`15189e6a-c53c-48f7-bad9-149132657221`, Transport in Plants.
Both content and v1 lesson reads returned HTTP 200: 12 sections, six checkpoints,
three assessment questions and eight images. The production audit records the
targeted question repair succeeding in 4.4 seconds.

This is a successful upload/save/read, not full media recovery. All 12 sections
have audio-generation failure notes; production reports YarnGPT QUOTA_EXCEEDED.
Seven sections qualify for depth rewrites: all seven have Expand, five have
Simplify. Simplify for sections 3 and 4 was rejected for missing source-claim
anchors. Five shorter sections do not qualify for depth generation. No teacher
approval or class assignment was performed. The generation latency remains a
performance gap and is not represented as resolved.
