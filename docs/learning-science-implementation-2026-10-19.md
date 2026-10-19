# Learning-science backend fixes - 19 October 2026

## Scope and rollout

Backend only. No frontend files were edited. This is not a declaration that the
entire learning-science paper is now empirically established or implemented as
a trained neural model.

Migrations, in order:

- `20261019_0106`: durable, unique concept/session review evidence.
- `20261019_0107`: allow calculation answer attempts through the database source constraint.
- `20261019_0108`: BKT transition parameter and model provenance; existing beliefs
  retain `legacy_v1` until a qualifying update, rather than being silently recomputed.

Render's start script runs `alembic upgrade head`. Code push is not evidence of
deployment or successful production migration. Test databases are disposable
local PostgreSQL, never the configured customer database.

## Audit disposition

| Gap | Implemented | Remaining boundary |
| --- | --- | --- |
| G01 baseline reduction | Separate measured-dimension summaries; optional `sequenceLength` and `dotRatio`; flanker interference changes the delivery window; ANS results influence initial numerical visuals. Motor subtraction is limited to processing/attention timing, not passage reading duration. | Device-generated tasks still supply their verdict where there is no server bank key. Age-band psychometric calibration, complex-span task design and oral-fluency validation are not invented. Derived windows are provisional delivery rules, not measured clinical attention spans. |
| G02 warm-up | Server-owned domain questions recalibrate placement and baseline; optional device `trials` update just the measured dimension; completion and changes commit once under a user lock. Domain selection is restricted to enrolled subjects. | The frontend must send device results to use this transaction; an old completion-only call remains supported but explicitly returns `receipt_only`. |
| G03 probe model | Local Rasch 1PL IRT with a grid posterior, EAP estimate, posterior-expected item information, uncertainty and bounded stopping. Resume uses recorded historical item difficulty. | Item parameters are explicitly provisional, not a fitted/calibrated school population. |
| G04 BKT | Bayesian observation update using prior, guess, slip and transition. Guess now changes the posterior. Version/transition persisted. | Parameters need school-data evaluation; reading attribution remains a disclosed heuristic, not trained AKT. |
| G05 AKT | Stored, same-school prerequisite mastery is wired into the live attempt path. Removed the claim that the compatibility class name implies a trained deep model. | No trained AKT model is active. See the reuse assessment below; synthetic/random weights are not an implementation. |
| G06 curriculum graph | Typed readiness read identifies assessed mapping errors, authored-check gaps and an entirely unlinked graph. Explicit segment mapping fills missing question/calculation links without overwriting existing authored concept choices. Existing prerequisite writes retain cycle validation. | No approved prerequisite map was supplied. No dependencies are invented or auto-approved. School/subject owners must populate and approve them. |
| G07 fading | Hint-dependent success does not fade; slow but accurate unaided work is not penalised. The starting state comes from the session delivery setting; calculation evidence aggregates all steps and hint use. | Frontend dots must follow returned state; no frontend change was made. |
| G08 pacing | Typed `readingGroups` are produced from the frozen session configuration in online and offline delivery, preserving chunk IDs/offsets. The attention window affects break monitoring. Curriculum readiness exposes authored-check shortages. | New reading groups require frontend consumption. Check gaps require authored/reviewed content; the browser must not fabricate questions. |
| G09 fidelity | Conservative source-claim anchor screening supplements numbers/equations; source claims accompany new rewrites. All generated/unknown-review rewrites default pending; student reads and proactive actions require explicit named/date-stamped approval. | This screening is not a proof of semantic equivalence. Teacher review remains essential, including expanded-topic scope and valid paraphrases rejected conservatively. Historical pending variants are not auto-approved. |
| G10 calculation marking | Marking snapshots preserve options and both legacy accepted-form names; distractor aliases cannot bypass the same filter used for delivery. Fixed the previously incompatible database source constraint. | Historical calculations without usable interactive data retain source fallback, not fabricated steps. |
| G11 spaced review | Completion derives recall from stored first answers, timing and hints; existing schedules update transactionally once per concept/session. Retries return durable evidence. Late old evidence cannot rewind a newer schedule. | Student callers must have a completed session with marked evidence; outcome/boolean/time supplied by a device cannot override it. |
| G12 learner-safe reads | Baseline estimates no longer returned; mastery/reading probabilities, attention weights and memory parameters are withheld from student responses. Progress copy and required player controls remain. Class/school mastery aggregates explicitly exclude students. Probe entry estimate remains server-side. | Frontend must tolerate the documented null fields; this does not certify every browser view. |

## Frontend contract handoff

### Warm-up

`POST /api/baseline/recalibrate-prompt/{studentId}/response` accepts the existing
`itemId`/`value` form for served domain questions. Device days may also send:

```json
{
  "formFactor": "tablet_touch",
  "trials": [
    {
      "dimension": "reading",
      "correct": true,
      "responseTimeMs": 30000,
      "readingWordCount": 30
    }
  ]
}
```

Trials must match today's dimension. `not_sure` and unmarked/skipped trials do
not become misses. The receipt includes `measurementStatus`:
`recalibrated`, `unavailable`, or `receipt_only`. A repeat does not recalibrate
again. Missing device data is not described as a measurement.

Baseline trial ingestion also accepts `sequenceLength` and `dotRatio` when
actually observed. Do not infer or fabricate either. `baselineProfile` is now
an empty object on student submissions; `engineConfig` still carries the
required player directives.

### Reading delivery

Each segment's `readingGroups` contains `{id, chunkIds, wordCount, pauseAfter}`.
Render groups using the existing immutable `readingChunks`. Do not replace
annotation anchor IDs or calculate a different grouping in the browser.
Smaller grouping uses the existing minimum source units (normally at most
80 words); a legacy oversized source unit is not silently re-anchored.
Both lesson reads and offline packages carry groups. A new session captures
updated delivery settings; an existing session retains its snapshot.

### Curriculum

- `GET /api/v1/curriculum/readiness`: school-scoped staff read with typed findings.
- `PUT /api/v1/segments/{segmentId}/concept`: `{conceptId}`, explicit staff mapping.
- Existing `PUT /api/v1/concepts/{conceptId}/curriculum`: position and prerequisites,
  school validation and cycle rejection.

The readiness report is a review surface, not permission to manufacture a graph.
Its check-coverage warning uses three consecutive sections as the standard
content-coverage threshold; more frequent needs still require reviewed material.

### Reviews

Lesson completion now updates memory without a separate client callback.
For the compatibility `POST /api/scheduler/record-review`, send `sessionId` with
the student/concept when available. For student tokens, the server resolves a
completed sitting with actual marked answers and ignores caller verdicts and
backdating. Without evidence: `409 detail.code = review_evidence_required`.

Repeated requests reuse the ledger. Student responses retain next due date and
lesson/concept IDs; internal stability/difficulty/retrievability and the recall
verdict are null. Authorised staff reads retain their existing internal fields.
Review routes enforce the learning-consent gate.

### Scaffold compatibility write

For student tokens, `POST /api/intelligence/scaffolds/attempt` now requires
`answerAttemptId` from a saved lesson answer. Normal lesson attempts already
update support; this compatibility call returns the recorded state without
applying another change. A client verdict or supplied intensity cannot fade
support. Missing evidence is `422 server_marked_attempt_required`; an
unfinished calculation is `409 scaffold_evidence_pending`.

### Review and privacy

New rewrites carry `sourceClaims` and remain pending. A missing review status or
missing reviewer identity/date is not approval. The existing segment approval
route records the reviewing professional. A phrase-anchor screen can reject
valid paraphrases; the source remains available rather than shipping uncertain
content.

Student mastery/progress probability fields and probe `entryPoint` are nullable
and withheld. Do not derive a replacement score. Functional progress, next work,
authored answer feedback and delivery settings remain available.

## AKT reuse assessment

Deployment decision: reuse pyKT as a pinned dependency in a separate, locally
hosted ML worker, not by copying its entire repository into the FastAPI app.
The project supplies model/training code, not a managed prediction API. Any
internal inference API would be hosted by Nevo; learner sequences need not be
sent to an external model provider. Do not enable neural inference until a
compatible checkpoint, vocabulary and evaluation results exist.

Recommended implementation base: [pyKT](https://github.com/pykt-team/pykt-toolkit),
an MIT-licensed toolkit with an AKT implementation and training/evaluation
workflow. The [authors' AKT implementation](https://github.com/arghosh/AKT) is the
reference alternative, useful for checking the published architecture.

The [pyKT quick start](https://github.com/pykt-team/pykt-toolkit/blob/main/docs/source/quick_start.md)
describes dataset preprocessing, training and evaluation; it is not a universal
model service. The [AKT model](https://github.com/pykt-team/pykt-toolkit/blob/main/pykt/models/akt.py)
uses concept/question vocabularies and response histories. Inference: checkpoint
embedding indices from a benchmark do not automatically identify Nevo concepts.
Stock AKT also does not establish Nevo's separate reading-confound attribution.

To activate genuine AKT, rather than an untrained architecture:

1. Approve the school concept vocabulary and lawful training purpose.
2. Prepare minimised, pseudonymous concept/question/response sequences; do not
   export names, emails, chat text or raw touch traces. No data export or model
   upload was performed as part of this change.
3. Train/evaluate in a separate pinned ML environment; do not add large training
   dependencies to the request-serving process without memory/latency testing.
4. Split by learner and time to avoid leakage; compare BKT against AKT for
   calibration, predictive quality and reading-confounded cases.
5. Run a versioned model in local shadow inference; promote only after agreed
   acceptance criteria. Preserve BKT fallback for unknown/unmapped concepts.

No externally trained checkpoint has been represented as validated for Nevo.
The current production-capable algorithm in this patch is versioned local BKT
with provisional reading attribution and related-skill support.

Mathematical references: [Corbett and Anderson's knowledge-tracing paper](https://perso.liris.cnrs.fr/pierre-antoine.champin/2014/m2iade-ia2/_static/893CorbettAnderson1995.pdf),
[Rasch probability model](https://rasch.org/rmt/glossary.htm), and
[EAP estimation](https://rasch.org/rmt/rmt163i.htm).

## Explicitly not closed

- Trained/evaluated deep AKT and its reading-attribution extension.
- An approved school prerequisite graph; there was no authorised map to backfill.
- Validated age-band psychometric transforms and oral-reading scoring.
- Frontend use of the new device-results/reading-group contracts and local
  affective-helper retirement/grace fixes (frontend was intentionally untouched).
- Teacher approval of existing rewrites and proof of educational effectiveness.

These are dependencies or separate validation work, not hidden placeholder
implementations. The earlier audit PDF remains a dated pre-fix snapshot; use
this disposition alongside it, not as evidence that all twelve items are closed.

## Verification

Follow-up: the live OpenAPI now exposes curriculum readiness. Review evidence
also uses persisted attempt numbers rather than timestamp/UUID ordering to
identify first and last answers, including bulk/offline saves.

- 161 selected tests passed, including real FastAPI/HTTP and disposable PostgreSQL
  tests for calculation marking, scaffold receipts, warm-up idempotency, review
  retry safety, curriculum mapping, and matching online/offline reading anchors.
- Existing coverage also exercised mastery, scheduling, adaptation limits,
  accommodations, parsing, depth review and source-claim screening.
- Migrations 0106, 0107 and 0108 upgraded the disposable database successfully.
- Ruff and whitespace checks passed. The test run retains the existing
  Starlette/httpx deprecation warning; it is not an endpoint failure.
- No real school answers, model training data or external media generation were
  created to make tests pass. No production endpoint behaviour is claimed before
  the deployed code has been verified.
