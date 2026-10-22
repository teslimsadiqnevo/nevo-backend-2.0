# Controlled unchanged Osmosis re-upload

## Production rerun passed

After deployment of `9b76c50`, the exact retained PDF was posted to the public
`https://api.nevolearning.com/api/v1/uploads` endpoint on 22 October 2026,
19:38:07 to 19:38:25 UTC. The response returned the original upload and lesson,
status `ready`, stage `ready_to_assign`, and `reused: true`.

| Media | Provider calls | Cache hits | Asset writes | Retries | Failures |
| --- | ---: | ---: | ---: | ---: | ---: |
| Narration | 0 | 6 | 0 | 0 | 0 |
| Images | 0 | 4 | 0 | 0 | 0 |

This supersedes the deployment caveat on the earlier local test below. It proves
the unchanged-source reuse path is operating on the public API. The report's
whole-day totals also include earlier local-handler verification runs; the table
above is only the public-API rerun's window.

## Follow-up fix and successful handler test

The `selection` choice alias is now classified using its answer cardinality and
validated against actual options. Unknown renderers and unmatched answers still
fail preparation; no question is silently discarded.

Staged uploads now reuse an existing ready upload for the same uploader, school,
scope and subject when the retained file bytes match. New text imports also keep
a deterministic source/settings fingerprint, and concurrent matching processing
requests return the same job rather than starting another parse. Existing content,
teacher edits and approval records are retained. `UploadCreatedResponse.reused`
explicitly identifies reuse. This is idempotent reuse of the original lesson, not
a new editable copy or permission to share a different school's lesson.

The new handler was exercised over multipart HTTP using local ASGI execution,
real test-school authentication, the original retained PDF and the production DB
and media ledger. Latest window: 22 October 2026, 19:33:06 to 19:33:25 UTC.
All ten referenced storage objects were verified to exist before this repeat.

| Media | Provider calls | Cache hits | Asset writes |
| --- | ---: | ---: | ---: |
| Narration | 0 | 6 | 0 |
| Images | 0 | 4 | 0 |

The response returned original upload `f797428f-2674-4584-81f6-919b28110e5d`,
status `ready`, `reused: true`, and original lesson `3367de9d-be40-4704-8a95-7a197b9824dc`.
No parsing, safety-model, image-generation or narration-generation call was made
by that reused request. Cache hits count reused stored references; as with the
report inventory, they are not a periodic bucket-integrity audit.

The updated handler still needs deploying on Render. This local HTTP test must
not be represented as proof that Render is already running the new code.
No migration is required beyond existing 0112. The earlier failed production test
is retained below rather than rewritten as a success.

## Earlier production failure (before this fix)

Production test on 22 October 2026, 19:19:13 to 19:20:33 UTC.

Original retained upload: `f797428f-2674-4584-81f6-919b28110e5d`.
Original lesson: `3367de9d-be40-4704-8a95-7a197b9824dc` (not modified).
File: `Osmosis.pdf`, 6,684 bytes.
SHA-256: `148d806ca719293f44a4bec0e9a081a4ed8a4021bc7257d3425b24c014766855`.
The exact retained bytes, filename and content type were posted to production
`POST /api/v1/uploads`; no reconstructed text or edited document was used.

Test upload: `2fe38c95-ad60-4361-a5e7-9ed09684c695`.
Result: failed at `finding_sections`; incident `f23e53925ead`.
Stored cause: `Unsupported question type in 1: selection`.

The media report for the observation window returned no groups:

| Metric | Count |
| --- | ---: |
| Media provider calls | 0 |
| Cache hits | 0 |
| Asset writes | 0 |

This is NOT a successful cache-reuse test: question validation prevented the
upload from reaching media preparation. No conclusion about unchanged-upload
reuse can be drawn from these zeros. Do not report this as a zero-cost upload:
lesson parsing made AI calls outside the media ledger.

## Earlier adapter-only behavior (before source reuse)

Audio storage lookup is keyed by configured voice and normalized script (first
2,000 characters). Image lookup is keyed by safety policy version, image model
and generated prompt. The original PDF hash is not a whole-upload reuse key.
Re-parsing unchanged bytes can produce different scripts/prompts and therefore
new generation. Exact matching assets are reused; cached images still undergo
safety checks, which may cost money.

The targeted Osmosis narration repair script skips sections that already carry
an `audioUrl` and only attempts missing narration. The audio adapter additionally
checks deterministic storage paths. A stale URL reference is not itself proof
that the object still exists.

Full lesson `/regenerate` is different: it re-parses stored segment bodies and
attempts media preparation for the resulting sections; it is not missing-only.
Image re-review checks existing bytes rather than drawing another picture.
Consequently, "explicit repair" must name the operation; there is no blanket
guarantee that every repair operation is missing-only.

## Synthetic accounts

At the user's explicit request, Bayo, Chidi, Dara and Efe (`NV-SS1SCI02` through
`NV-SS1SCI05`) have onboarding module completion recorded as synthetic demo
fixtures, with no invented measurements or subject placements. Amina
(`NV-SS1SCI01`) was left unchanged.
