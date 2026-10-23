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
