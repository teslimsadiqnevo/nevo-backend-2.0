# Backend fixes not waiting on model or content approval

19 October 2026 | Backend only

## Completed in this follow-up

- Baseline ingestion no longer turns an unmarked device trial into an incorrect
  answer. Missing bank-item responses, skipped tasks and explicit declines are
  excluded from scored evidence. Genuine marked incorrect answers still count.
- Partial speed recalibration requires an actual timing before replacing an
  existing speed/latency estimate; a timing-free result does not substitute a
  default for a previous measurement.
- An ANS-only warm-up now updates its numerical-visual delivery setting without
  losing it during the support merge or resetting unrelated scaffolding settings.
- Session snapshots preserve existing shorter-text, pause and step-by-step
  delivery settings when no new accommodation evidence is present. Accommodation
  inference can still add support, and a lower-depth reroute still applies its
  stronger delivery constraints. A saved session snapshot remains frozen.
- Next-work selection now resolves a real mapped section from an available,
  completed, same-school assigned lesson. It recognises explicit checkpoint and
  calculation mappings as well as the segment mapping; missing direct mapping
  does not hide otherwise valid authored work.
- It no longer uses an arbitrary first section or an unassigned concept-origin
  lesson as fallback. Cancelled/future assignments, unfinished lessons, unresolved
  flagged content and unsettled key points are not proposed. If no deliverable
  mapped work exists, the existing nullable response returns null.

These changes do not manufacture curriculum dependencies, questions, model weights
or teacher approval. No new public fields, routes or migrations are required.

## Deployment check

Before this patch, the live health read reported expected/applied schema
`20261019_0108`, `up_to_date`. The live OpenAPI also declares `reviewedByName` on
`DepthVariantBody`, confirming the previous additive contract is deployed. This
does not certify provider recovery or frontend rendering.

## Verification

Focused FastAPI/HTTP tests run against disposable local PostgreSQL, with no AI
key or real-school writes. Regressions cover baseline missingness, partial
recalibration, persisted session settings, explicit question mappings, placement
routing and refusals to recommend undeliverable lessons. Broader local coverage
also exercises BKT, probing, scaffolds, scheduling, accommodations, adaptation
guards, content parsing, rewrite approval and online/offline reading anchors.

Result: 174 selected tests passed. Ruff passed; the existing Starlette/httpx
deprecation warning remains, with no test failures.

## Still external or explicitly deferred

- AKT process approval, training and evaluation.
- Authoritative prerequisite links and authoring of genuinely missing checks.
- Scientific/psychometric validation and oral-reading task/scoring specification.
- Teacher approval of pending rewrites.
- Frontend adoption and browser verification of the documented contracts.
- Audio/image provider credits and quota recovery.

Those are not silently marked complete by this backend patch. No frontend files
were edited, no teacher approval was granted, and no production school data was
rewritten or exported.
