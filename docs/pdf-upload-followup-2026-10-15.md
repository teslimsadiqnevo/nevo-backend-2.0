# PDF upload follow-up, 15 October 2026

## Confirmed PDF failure

The retained source for upload `43164ffe` contains 34,936 characters. The old
paragraph packer admitted a single oversized paragraph, bypassing its budget.
The corrected splitter produces six chunks of 5,005, 5,684, 5,668, 6,069, 6,236
and 6,274 characters, each below the 6,553-character cap. It prefers page markers,
then paragraphs, lines, sentence/word boundaries, with a final hard bound even
for an unbroken line. Multi-chunk section and checkpoint identifiers are namespaced
to prevent collisions between independently generated chunks.

Fallback also uses bounded sections and no longer silently stops at 80 parts.
The retained PDF produces 27 fallback sections, the largest 1,797 characters,
instead of one 7,353-word section. Page markers are not used as section titles.
Fallback is still flagged for teacher review; splitting is not a claim that the
AI successfully structured the document. Existing stored lessons need a fresh
parse to obtain the corrected structure.

## Missing-page semantics

`failedPages` means text could not be extracted, not that an AI response failed
JSON validation. Blank extracted pages are recorded with `page_text_missing`.
`ai_parse_fallback` notes retain page provenance and `textRetained: true` but do
not contribute to `failedPages`. Thus the console must not describe retained
fallback text as absent.

## Retry

The reported retry has finished: upload `43164ffe` was read as `ready`, with
lesson `aa4dadae-20cb-4ebf-bc98-1f82f6272309`. That was produced by the earlier
deployment, not proof of the new splitter running in production.

Retry now uses the same bounded parser and rebuilds from the retained full PDF
so replacing the structure does not discard unselected pages. It is not yet an
incremental merge of only selected pages. The request still reports which pages
were requested in `pagesRetried`. Concurrent retries are refused with 409
`upload_already_processing`; processing is capped at 20 minutes and records a
terminal failure if it times out. This does not promise a large PDF finishes in
under seven minutes, nor provide durable resume after a worker restart.

## Audio 404

The prior adapter discarded the provider error code, so a generic 404 cannot
identify a missing route, retired voice or missing job. Failures now include
method/path, provider code and trace id. A specific POST `VOICE_NOT_FOUND` gets
one fallback to the provider-selected voice, with a different idempotency key
because the body changed. Other 404s are not retried as voice errors.

Both current documented TTS and voice routes answered 401 to unauthenticated
route probes. This confirms route reachability, not successful synthesis or the
cause of production's 404. No YarnGPT key is configured in the local environment,
so authenticated end-to-end generation remains unverified. The next production
failure must retain its exact provider code/trace rather than be called a quota
problem. The returned voice is null when the exact delivered voice is unknown.

Reference: https://yarngpt.ai/api-docs

## Recovered starch activity

The E2E record in `319f2cd2` was updated again: the activity uses the actual
section title, introductory prose is in optional `introduction`, only procedural
instructions are steps, and the observed result is the `outcome`. The source
safety warning is attached to the first actionable instruction so older activity
renderers cannot accidentally omit it. Teacher approval remains required.

## Verification

45 focused tests passed, covering hard chunk caps, text preservation, the
27-page case, missing-page semantics, retry source preservation, retired-voice
fallback and distinct 404 diagnostics, plus existing upload polling contracts.
Lint passed. No schema migration or frontend code change was made.
