# Z-guide read and preparation follow-up

## Read failure: repaired

Lesson `4c2c9055-2b94-4fad-a8ef-5251c0a6ca3e` had two metadata problems:

- Sections 1, 28 and 32 held visual proposals (`conceptual_diagram`, `table`,
  `error_tree`) in the generated-image field without image delivery metadata.
- Equation callouts in sections 28, 29, 31 and 32 used `person-authored`, outside
  the response enum `person | nevo`.

The targeted E2E repair corrected seven metadata fields without deleting or
rewriting any of the 45 sections. The complete content lesson-detail handler
was invoked locally with the lesson creator's principal and its full response
validated and serialized successfully. This is not a deployed HTTP probe.

Future writes clear non-image proposals from the bitmap field even when that
field is not advertised as a modality. Calculation scaffolds remain available
through their calculation payload. Lesson reads also tolerate invalid bitmap
metadata rather than losing the whole lesson. Known authorship aliases are
canonicalized at write/read boundaries without changing the public enum.

## YarnGPT quota refusal

`402 QUOTA_EXCEEDED` requires account funding; neither backoff nor a new voice
adds credits. After a 402, the worker pauses further provider attempts for that
API key for five minutes, including across service instances. Existing cached
Supabase clips remain usable. This is an in-worker circuit, not a distributed
account-wide lock across hosts. Suppressed clips still record that audio was
not prepared, but are not additional upstream synthesis requests.

## Pass seams and elapsed time

Parsing previously awaited each document pass sequentially. It now permits two
concurrent passes through the existing gateway scheduler, preserving source
order when assembling the results. Media has its own limits and is not made
unbounded: depth rewrites use four slots, images two, and YarnGPT has a shared
worker queue.

Passes receive bounded preceding/following source context and explicit rules
that they are parts of one lesson. Headroom is reserved so that context does
not bypass the input cap. Only the final pass is asked for the final assessment.
Clearly titled lesson recaps, wrap-ups, conclusions and key takeaways are kept
in the end recap instead of interrupting the teaching sections. Exact repeated
section bodies are omitted; title similarity alone never deletes content.

These changes reduce serial waiting and discourage repeated introductions;
they do not guarantee semantic deduplication or a fixed completion time. The
existing 45-section lesson has not been reauthored: reparse it to obtain the
new seam treatment. No genuine teaching content was discarded in the repair.

## Depth rewrites

Parse/depth requests explicitly request complete JSON with escaped mathematical
notation. Depth output budgets scale with source length, and malformed or
token-truncated replies receive one bounded retry with a larger budget.
Rewrites still fail safely to the original text after that retry. The checks
against invented numbers, unchanged text and incorrect length direction remain
in place: quality rejection is not bypassed to make a completion count look good.

The exact causes of the two historical quality rejections cannot be recovered
from the generic old note; no more specific diagnosis is claimed.

## Verification

77 focused tests passed; lint passed. Coverage includes two-pass concurrency,
bounded context, end-only recap assembly, metadata read compatibility, depth
retry, audio quota suppression, PDF bounds and existing media concurrency.
No database migration or frontend code edit is required. Production deployment
and a timed full-document reparse remain separate verification steps.
