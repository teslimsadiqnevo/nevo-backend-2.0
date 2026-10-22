# Controlled unchanged Osmosis re-upload

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

## What the implementation currently guarantees

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
