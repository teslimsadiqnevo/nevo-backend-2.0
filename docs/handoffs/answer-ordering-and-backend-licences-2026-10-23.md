# Answer ordering and backend licence notices

## What changed

Choice ordering is now an explicit presentation operation, keyed by the pupil,
question and section rather than an implicit response-model side effect.
Online lesson reads, offline packages and persisted question-attempt snapshots
use the same order. Reloads do not move the choices. The answer key remains
attached to the option value, never its displayed position. Response validation
does not shuffle a second time. This applies to existing stored content as well
as future uploads, without regenerating lesson content or altering past marks.

## Production-data sweep

The sweep inspected all stored quick checks and assessments, and every active
backend onboarding knowledge-bank item, on 23 October 2026.

| Source | Items | Result |
| --- | ---: | --- |
| In-lesson quick checks | 353 | 343 valid choice questions, five non-choice questions, five unmarkable legacy fallback prompts |
| After-lesson checks | 68 | All valid choice questions |
| Onboarding knowledge bank | 8 | All have a matching correct option and pupil-specific ordering |

The five unmarkable fallback prompts have no answer key. Their five old imports
were marked failed and their affected sections' approvals cleared in the database.
The source and history are preserved, and a teacher-facing re-upload note is
recorded. The new student-read/adaptation guards refuse these imports with
`409 lesson_content_requires_review`; deploy this release for those guards.
No fabricated keys or replacement questions were introduced.

Affected lesson IDs:

- `166a173f-ffe3-476a-abc0-8eb95695d0e6`
- `5c6d3998-3c38-4eb6-84e9-894dd5bb5309`
- `92e17dd3-8d50-42cf-92bd-b609e8bfd77a`
- `ce9e0224-4f3d-4ced-bc5f-60f8681cd4fc`
- `f51222e2-e6c9-4269-aaee-3f1f8d2c3cce`

For synthetic Amina, Osmosis quick-check correct positions in section order are
`1, 3, 2, 2, 3`; its after-lesson positions are `3, 2, 1, 2`.
Across the 343 choice checks, positions 1/2/3/4 occur 92/98/93/60 times for
that pupil; after-lesson positions occur 11/20/27/10 times. Questions have
different option counts; these are observed counts, not a statistical validation.
The eight knowledge-bank positions occur 2/4/2 times at positions 1/2/3.
A correct answer may legitimately be first on an individual question.

Backend knowledge probes are covered. The other onboarding activities are
rendered on the device and send trials rather than receiving answer-option lists
from this backend. Yinka must confirm their deployed presentation/counterbalancing;
this sweep does not certify frontend behaviour. No frontend files changed.

Re-run read-only with `python scripts/audit_answer_ordering.py`; the explicit
`--quarantine` option persists failed status for imports with invalid checkpoints.

## Public backend licence page

Fixed URL after deployment:
https://api.nevolearning.com/legal/third-party-licenses

The `.json` and `.txt` variants at the same path provide a typed inventory and
downloadable notices. No sign-in is required. The inventory follows installed
runtime dependencies, including transitive extras, and excludes development-only
dependencies. All 36 dependencies in the tested environment have full notices.
Missing distribution notices are gathered at build time from exact-version,
checksum-verified sources; missing notices fail preparation rather than silently
publishing an incomplete inventory. No network fetch happens when viewing it.

Build using `bash scripts/render-build.sh`, or append
`python -m nevo.legal.prepare` after the existing install command.
The Docker image and CI also run preparation. No database migration is required.
The fixed URL must not be represented as live until Render deploys this commit.

Yinka: this page covers the backend only. Generate the frontend dependency notices,
including sharp/libvips and their applicable distribution obligations, on the
frontend side and link both inventories from the product's licences page.
Backend publication alone does not establish compliance for frontend binaries.

## Still parked

AWS provisioning and restore jobs remain blocked by the missing separate account
and billing arrangement, deferred until after the demo. Vercel Observability Plus
activation is not verified. No evidence-retention clock has been changed; counsel
must define the separate evidence period and its lawful scope before implementation.
Token terminology remains awaiting clarification. None of these are claimed complete.
