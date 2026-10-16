# Z-guide follow-up, 16 October 2026

## New lesson read failure

The new lesson `d1d52470-c99d-4c40-8336-d6cec430bd4a` contained arbitrary
publication/source values (`Cosmic`, `formal_specification`) in the renderer's
`authoredBy` classification. The earlier fix only canonicalized known aliases,
so these values still failed the closed `person | nevo` enum.

Generated key terms and equation aids now take provenance from the server-owned
generation path, never the model's author field. On legacy reads, an unsupported
child provenance value inherits the enclosing text variant's known provenance;
publication names are not treated as renderer classifications. Existing valid
classifications remain valid and the public enum is unchanged.

Every parsed segment's variant contracts and checkpoints are now validated
before the repository opens a write transaction or replaces existing rows.
Malformed variants cannot be saved as a successfully completed parse. Unexpected
invalid delivery data produces a failed preparation with the original upload
retained, rather than an unreadable completed lesson. The existing read guard
for non-image visual proposals remains in place.

The reported E2E lesson had 11 metadata fields repaired. Its complete content
lesson-detail handler response validates and serializes with all 59 sections
preserved; the earlier lesson also validates with all 45 sections. No section
body or attempt history was deleted. This was a direct local handler check
against the configured database, not a deployed HTTP probe.

## Description

The current stored and serialized descriptions for both reported lessons were
already prose summaries, not duration lists. The old lesson currently returns:

> This lesson introduces formal methods and the Z notation for specifying computer systems, building from basic set theory through to robust error-handling schemas.

The new description guard permits a short single-line content preview or null,
and rejects strings such as `Total: 99 min (Segment 1: 2 min, ...)` at parse,
write and response boundaries. Duration remains in `estimatedMinutes`.
If the UI still shows the duration string after the read works, compare its
actual response body and field mapping; the reported duration string was not
reproduced from the current backend data.

## Repeated titles

The retained PDF starts with a contents list spanning pages 1–2. Those headings
were being expanded into teaching sections, then taught again when the actual
chapter text arrived. The real source repeats formal-methods terminology on
pages 1, 3 and 20, and overriding on pages 2, 10 and 26; some later repetition
is therefore also genuine revision/reference material, not necessarily a seam.

New parses exclude a detected contents page and its immediate dotted-list
continuation from instructional input. This removes exactly pages 1–2 in the
reported file: 34,936 extracted characters become 29,931 instructional
characters. The original file is retained unchanged, and the excluded page
numbers are recorded as `source_navigation_pages`, not `failedPages`.

Title similarity alone still does not delete sections. Existing lesson bodies
have not been rewritten; a new parse is required for contents-page filtering.

## Verification

43 focused tests passed and lint passed. Tests cover arbitrary author strings
and non-string author values, legacy read normalization, pre-transaction write
rejection, one-line description filtering, contents-page continuations and
existing lesson/read contracts. No migration or frontend edit is required.
Production deployment and a fresh full-generation run remain unverified.
