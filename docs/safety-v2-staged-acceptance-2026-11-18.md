# Safety v2 staged acceptance, 18 November 2026

## Corpus and production evidence

The lesson-only corpus now has 42 cases, including twelve ordinary chemistry
and biology generated-output reconstructions. The twelve near-miss labels were
approved by Lydia; the six new reconstructions still need her review. V1 and
v2 each returned 42 expected verdicts, zero false blocks, zero unsafe misses,
and zero checker errors on this set. Matching outcomes do not demonstrate an
improvement over v1.

The live database currently has 70 historical block/safeguard events, not the
earlier count of 38. None of the 70 has full review text retained. The old
events cannot be presented as verbatim passages for retrospective labelling.
V1 generated-output blocks are now captured in the restricted review record
for 30 days, so future exact failures can be labelled. The Food Chains and
Separation of Mixtures source replay did not reproduce a block; see
`docs/safety-v1-source-replay-2026-11-18.md`.

## Offline contract

New offline packages and manifests carry `generatedAt` and `expiresAt`, with
a maximum age of fourteen days. `GET /api/v1/offline-downloads/{id}/status`
returns `current`, `expired`, or `safety_revoked`. A held section included in
the saved download revokes it; a legacy download whose included sections are
unknown is revoked when its lesson has any held section. The status route is
student-scoped and is designed for the player's first connection, before it
opens any cached content. The player must enforce that order and must refuse
to open a package past its embedded `expiresAt` while offline. The backend
cannot reach a disconnected device or enforce the client-side open rule by
itself. That offline window remains a documented residual risk.

## Local checks

- Held sections are absent from online reads and newly built offline packages.
- An existing download changes from `current` to `safety_revoked` when its
  included section is held; a fifteen-day-old download returns `expired`.
- A checker outage produces no safety event.
- A flagged review record's full text is actually deleted by the thirty-day
  expiry job, while its decision remains.
- Assignment refuses a lesson with a safety hold and names the outstanding
  review step.
- The image service refuses blocked media before upload/delivery.
- An unreviewed picture is omitted from the student modality list while its
  section's teaching body remains available.

These are local backend checks, not a complete device acceptance run. The
player's first-connection ordering and offline expiry handling, the exact
temporary outage wording through the upload UI, and teacher-side review of a
real held picture still require joint staged evidence.
V2 remains disabled pending that evidence and Lydia's approval.
