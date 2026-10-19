# Nevo knowledge tracing: deployment plan and frontend handoff

19 October 2026 | Backend engineering | Architecture proposal plus verified current state

## 1. The direct answer: BKT now, AKT next

**BKT is already integrated and runs locally inside the current backend. AKT is
the additional model we propose integrating through a Nevo-owned ML service.**
We are not looking for a BKT vendor API, and installing AKT code does not make
a trained AKT model available. The existing player can adapt without AKT.

Current BKT updates a concept belief from a saved, server-marked answer using
prior knowledge, guess, slip and learning-transition parameters. Scaffold
fading, break rules, rate limits, consent and scheduling are separate local
mechanisms. Reading-confound attribution remains a disclosed heuristic.

AKT learns response-sequence patterns with attention. Its output predicts a
response probability for a particular item/concept given history. That is not
automatically a calibrated mastery score, a diagnosis, an attention measurement,
or proof that an accommodation will help. Stock AKT does not implement Nevo's
special dual-skill reading attribution by itself.

The initial integration should run AKT in **shadow mode**: BKT remains authoritative,
AKT predictions are evaluated internally, and no child-facing behaviour changes.
Only a reviewed promotion decision permits AKT to influence decisions. Do not
average BKT and AKT probabilities arbitrarily or update the same observation twice.

## 2. The reusable codebase

Recommended base: [pyKT](https://github.com/pykt-team/pykt-toolkit), with its
[AKT implementation](https://github.com/pykt-team/pykt-toolkit/blob/main/pykt/models/akt.py)
and [training/evaluation workflow](https://github.com/pykt-team/pykt-toolkit/blob/main/docs/source/quick_start.md).
The [authors' original code](https://github.com/arghosh/AKT) is a reference
implementation for the [AKT paper](https://arxiv.org/abs/2007.12324).

pyKT is MIT-licensed code, not a managed prediction endpoint. Retain its licence
notice and pin a reviewed release/commit and transitive dependencies. Dataset
and checkpoint licences must be checked separately; the code licence does not
grant rights to every training dataset or school record.

Use it as a dependency in a separate service, not by copying its whole repository
into the web API or installing training dependencies in every Render web worker.
The exact compatible Python/PyTorch/CUDA combination is selected and locked during
the reproducibility spike; no untested version combination is prescribed here.

No pyKT service, trained checkpoint, training export, GPU job or neural inference
integration has been created by writing this plan. The current runtime remains BKT.

## 3. Proposed environment layout

### Existing public API

Keep the current FastAPI service at `https://api.nevolearning.com`. It owns
authentication, school boundaries, consent, answer marking, transactional learning
evidence, BKT, scaffolds, schedules and the public player contract. It remains
functional if the ML service is unavailable.

### Private AKT inference service

Run a separate container in a Nevo-controlled environment. Start with CPU inference;
an initial profiling target is 2 vCPU and 4-8 GB RAM, not a verified capacity promise.
Measure actual checkpoint memory, cold start, sequence lengths and concurrent load
before choosing production sizing. A GPU is optional for inference if benchmarks
justify it, not a dependency to open a lesson.

The inference service has no public browser endpoint and no direct client tokens.
Use private networking plus authenticated service requests. If private networking
is unavailable, use an authenticated TLS endpoint with network restrictions;
an obscure URL alone is not security. Keep its region and storage location aligned
with approved data-processing arrangements. Do not claim multi-region resilience
unless it is actually provisioned and tested.

Load one immutable, approved model bundle at startup. Readiness becomes healthy
only after the bundle, vocabulary, checksums and a fixed smoke fixture validate.
Liveness only proves the process is alive. Bound request size and sequence length.
No model training, internet downloads or checkpoint swaps during inference requests.

### Separate training job

Use a disposable batch environment, with a GPU only if it materially helps the
measured workload. Training dependencies and credentials must not live in the web
API container. Disable optional third-party experiment uploads by default; local
evaluation artifacts are sufficient. Do not send school sequences to an external
tracking platform without approval.

### Database and artifact storage

Supabase Postgres remains the source of authoritative marked answer evidence.
The ML inference service should not hold a general production database credential.
The API supplies a bounded minimised history, or an authorised worker prepares it.

Use a private Supabase Storage bucket for versioned model bundles and minimised
datasets. Never put them in public lesson-media buckets. Use short-lived scoped
access where supported; do not distribute the Supabase service-role key to every
worker. Bundle promotion and rollback are controlled operations, not overwrites.

### Local and CI

Use a separate virtual environment/container for ML. Use disposable Postgres and
synthetic fixtures in CI, never the real `DATABASE_URL` masquerading as a test DB.
Local BKT tests should not require PyTorch, an AKT model download or a GPU.

Suggested future layout, not existing files:

```text
services/knowledge-tracing/   private inference container and lockfile
ml/akt/                      dataset adapter, training and evaluation commands
src/nevo/mastery/            current local BKT plus future service adapter
docs/                        model card, promotion decision and runbook
```

## 4. How the backend links to AKT

### Online sequence

1. The child submits an answer to the existing backend; the server verifies
   ownership, consent and the authored answer key.
2. In the existing transaction, persist the answer and update BKT, scaffolds and
   review evidence according to their current rules. Preserve idempotency.
3. A future transactional outbox records that a sequence became eligible for AKT.
   The outbox avoids losing a job between database commit and queue publication.
4. A worker builds an ordered, bounded history of eligible marked attempts, maps
   concept/question UUIDs to the approved model vocabulary, and calls private AKT.
5. The worker records model version, vocabulary version, evidence version and
   prediction for shadow evaluation. An old prediction cannot overwrite newer
   evidence. Duplicate jobs reuse the same logical result.
6. Existing rule-based adaptation continues. In shadow mode the prediction never
   changes delivery. In a later approved mode it becomes one input to the same
   safety constraints, never a direct command to simplify or diagnose a child.

Prediction must be made *before* revealing the target answer to the model. Training
and evaluation adapters must respect AKT's shifted sequence/causal masking conventions;
otherwise answer leakage can produce convincing but meaningless accuracy.

The worker must recheck processing permission when executing a queued job, not
just when it was queued. A withdrawn child's job must not be processed later.
Do not include a full question, a transcript, touch traces or a child's name.

### Proposed private contract, not a shipped public API

```json
{
  "schemaVersion": 1,
  "requestId": "opaque-idempotency-key",
  "modelVersion": "approved-bundle-version",
  "vocabularyVersion": "approved-vocabulary-version",
  "evidenceVersion": 42,
  "history": [
    {"conceptIndex": 12, "questionIndex": 73, "correct": true},
    {"conceptIndex": 14, "questionIndex": 79, "correct": false}
  ],
  "target": {"conceptIndex": 14, "questionIndex": 80}
}
```

```json
{
  "requestId": "opaque-idempotency-key",
  "modelVersion": "approved-bundle-version",
  "vocabularyVersion": "approved-vocabulary-version",
  "evidenceVersion": 42,
  "status": "predicted",
  "predictedCorrectProbability": 0.68
}
```

An unmapped concept, insufficient usable history or incompatible vocabulary returns
an explicit unavailable reason, not a fake 0.5 or a successful random prediction.
Non-finite/out-of-range outputs fail validation. Internal probability fields never
go to the student UI. Cold starts and service errors use BKT fallback, not a lesson
failure. Bound timeouts, retries, queue age and concurrency and add a circuit breaker.
For shadow jobs, this is asynchronous and need not add a public request deadline.

Suggested routes are `/internal/v1/predict`, `/live` and `/ready`; these are design
proposals, not endpoints the frontend should integrate against.

## 5. What data is needed before training

Use persisted server-marked interactions tied to stable concepts/questions and
ordered attempts. Define an observation policy before extraction: a wrong answer,
hint-assisted correction and genuinely independent answer are not interchangeable.
Deduplicate retries. Do not turn a decline, missing answer or skipped task into a
miss. Preserve calculation step identity without overweighting a long calculation
relative to a short checkpoint; document the unit of observation.

Concept UUIDs are not neural embedding indices. Create a versioned mapping and an
unknown-ID policy. A benchmark checkpoint cannot be made Nevo-compatible just by
renaming its concept indices. New/deleted/merged concepts require explicit mapping
and model-version handling, not silent index reuse.

Training records need only a run-scoped pseudonymous learner key, concept/question
indices, response outcome and ordering. Exclude direct identifiers, free text,
credentials, raw touch and retired affective labels. Pseudonymised data is still
personal data, not automatically anonymous. Restrict the mapping separately.

Before using real school data: approve purpose, access, lawful basis, retention and
deletion obligations with the data owner/DPO. Explain what withdrawal means for
queued jobs, datasets, artifacts and already trained weights; deleting a row does
not automatically remove its influence from a trained model. Resolve that policy
before claiming a deletion/unlearning guarantee.

An approved prerequisite graph is separately needed for curriculum routing, but
is not itself a technical prerequisite for stock AKT training. AKT needs reliable
concept identity and eligible response histories. Do not confuse the two blockers.

## 6. Training and acceptance

First inspect usable evidence counts and coverage without exporting identifiable
records. No claim is made here that Nevo already has enough real data. Synthetic
fixtures prove software wiring only; they do not establish predictive value.

Use deterministic preprocessing, a frozen vocabulary, seeds, code/dependency hashes
and a manifest of dataset scope. Hold learners out and respect time ordering; use
a validation set for tuning and an untouched test set for the final comparison.
Avoid putting the same learner's near-duplicate interactions across splits.

Compare AKT against current BKT and simple baselines using log loss, Brier score,
calibration and AUC where both outcomes exist. Report sample counts, uncertainty,
coverage and performance for cold-start/sparse histories and hinted versus unaided
work. Do not claim a reading-confound model merely because aggregate AUC improves.

Proposed promotion gates, subject to owner approval:

- Reproducible artifact and vocabulary; no target leakage or incompatible indices.
- Better held-out predictive/calibration results than the baseline, with uncertainty
  and important subgroup regressions reviewed rather than hidden by an average.
- Acceptable load-test memory, latency, error rate and fallback behaviour.
- Privacy, consent, school-isolation and deletion policy checks complete.
- Shadow results reviewed and product approval for exactly which decision may use
  the model; retain hard multi-signal, dwell, cooldown and maximum-shift guards.
- A model card, named approver, rollback bundle and operational runbook exist.

Prediction quality and educational benefit are different claims. Validate learning
benefit separately; a higher AUC alone does not prove improved attainment.

## 7. Configuration and operations

These are proposed environment names, **not settings supported by today's app**:

```text
KT_MODE=bkt                 # bkt -> shadow -> approved hybrid policy
AKT_INTERNAL_URL=...        # private service only
AKT_SERVICE_TOKEN=...       # independent service credential, never in frontend env
AKT_MODEL_VERSION=...
AKT_VOCABULARY_VERSION=...
AKT_BUNDLE_URI=...          # private immutable artifact location
AKT_BUNDLE_SHA256=...
AKT_REQUEST_TIMEOUT_MS=...
AKT_MAX_SEQUENCE_LENGTH=...
```

The adapter must enforce the configured mode; a model response cannot promote
itself. Do not use Anthropic/OpenAI/YarnGPT credentials for this local model.
No commercial inference key is required for pyKT itself; infrastructure and
training still have costs. Pricing depends on measured usage, not a fixed promise.

Metrics: eligible/mapped coverage, unavailable reasons, queue age, inference latency,
failures, fallback rate, model/vocabulary versions, drift and held-out calibration.
Operational dashboards should use aggregates, not named child prediction streams.
Scrub request payloads from logs, tracing and error reporting.

Trust only approved bundles. Pin checksums; do not load arbitrary uploaded PyTorch
pickle checkpoints. Use a reviewed safe weights-loading/serialization path and
validate the architecture against the manifest. Cache immutable bundles locally.

Rollback is a configuration change to BKT plus cancellation/quarantine of affected
shadow jobs; do not roll back or delete children's persisted answers. No AKT service
failure should prevent sign-in, lesson completion or consent enforcement.

## 8. Implementation sequence and demo priorities

Wednesday means 21 October 2026. This is engineering sequencing, not a promise of a
validated neural model by that date. The complete current Lydia checklist was not
re-supplied with this request; the ordering below follows the demo priorities quoted
by Yinka and must not be presented as a line-by-line sign-off of her whole list.

### Before the demo: use the working local engine

Priority 1: verify the chosen demo calculation is approved, has a valid scaffold,
and marks distractors correctly. Calculation answers and support changes must be
server-derived. The relevant backend fixes are shipped; frontend step rendering
must still be exercised end to end.

Priority 2: demonstrate support rising and fading using distinct eligible problem
evidence. Three qualifying unaided successes can reduce support; hinted success
cannot. A struggling answer restores support without penalty. Do not reset or
fabricate a real child's evidence just to make the demonstration look adaptive.
The session's initial level affects how many transitions a short demo can show.

Priority 3: use approved Simplify/Expand variants that passed checks and teacher
review. Generated-but-pending text is deliberately unavailable to a student. Source
claim screening is conservative, not proof of semantic equivalence.

Priority 4: clear onboarding/CI and own-class access blockers. The no-bank exception,
legacy evidence credit and SCRUM-252 routes already exist. Confirm the frontend
uses the personal seen action rather than support acknowledgement for Home cards.

Priority 5: coordinate nullable internal fields, optional device warm-up trials and
readingGroups with the frontend. These contracts have already landed; see below.
Media quota recovery remains outside this backend change.

### After the demo: AKT workstream

Indicative engineering effort, not elapsed completion guarantees: 1-2 days for a
pinned pyKT reproducibility spike, 2-4 days for authorised evidence/vocabulary
preparation, and 2-4 days for private service/outbox/shadow wiring. Training,
evaluation, data sufficiency and promotion can extend well beyond those estimates.
Do not add the ranges and promise a launch date before inspecting the data.

Curriculum owner review and psychometric validation run as separate workstreams;
neither should be represented as complete because endpoints and formulas exist.

## 9. Answers for the frontend team

### Onboarding: the exact no-bank contract

`GET /api/v1/students/me/onboarding` returns:

```json
{
  "complete": true,
  "modules": [
    {"id": "grid_span", "completed": true, "status": "completed"},
    {"id": "pattern_flanker", "completed": true, "status": "completed"},
    {"id": "sentence_dot", "completed": true, "status": "completed"},
    {"id": "domain_probe", "completed": true, "status": "unavailable"}
  ],
  "subjects": [],
  "nextModule": null,
  "probeSubjectId": null,
  "probePolicy": "one_available_subject"
}
```

This example assumes the earlier three modules are complete. No new `not_required`
status is used. If enrolled subjects exist but none has items, subjects still lists
them with `probeAvailable: false`. No placement is invented. Lesson entry is not
blocked by `domain_probe`; other missing modules, consent, assignment availability
and normal access checks can still refuse entry. The unavailable outcome is durable.

Run one available subject from the child's enrolled classes; use `probeSubjectId`
as the server's suggested first subject. One completed subject is enough for initial
onboarding. It does not establish knowledge in every other subject. An empty bank
for one subject does not waive module 4 while another eligible subject has items.

Existing children with credited first-three modules do module 4 only where a bank
is available. Migration 0105 credits earlier modules from real legacy completion or
lesson evidence, not account age/defaults. An account with no completion evidence
is not guaranteed a waiver. Do not tell the frontend all old children are exempt.

### Student-facing contract changes already landed

- `baselineProfile` is an empty object on baseline submissions.
- Student mastery/progress numerical estimates and probe `entryPoint` are nullable
  and withheld. Do not derive substitute scores or render null as zero.
- Player `engineConfig`, functional progress, due dates and authored feedback remain.
- Online/offline segments can carry `readingGroups` over immutable `readingChunks`.
- Warm-up receipts distinguish `recalibrated`, `unavailable` and `receipt_only`.
- Review/scaffold compatibility writes require persisted server evidence; normal
  lesson completion/answers already update these mechanisms.

These changes were already pushed in `d461b60`; they are not a future heads-up.
The backend should have explicitly flagged the nullability changes before rollout.
Use the implementation handoff for request examples and error codes. The frontend
was not edited, so coordinated UI verification is still required.

### Calculations and accepted answers

A valid calculation advertises `interactive` only. It does not invoke image
generation; the deterministic scaffold is part of that player, not an empty image
modality. Invalid/missing calculation data falls back to source text, plus audio
where available, with review required. If the frontend renderer itself fails, use
the supplied source body and report that failure rather than show an empty lesson.

On choice steps, `targets` lists the offered options. `acceptedAnswers` contains
only accepted representations of the correct answer. Distractor aliases are
filtered from delivery and server marking, including the legacy accepted alias.

### SCRUM-252 and the two seen acts

An own-class teacher can read profiles and
`GET /api/adaptations/student/{studentId}` without Learning Support. Unrelated
teachers cannot; a same-school holder has wider access. Administrators still need
Learning Support for adaptation history.

Use `POST /api/intelligence/flags/{id}/seen` for a teacher's Home tap. It records only
that staff member's read and clears only their unread view. Read `seenByMe`/`seenAt`
and use `unseenOnly=true` for unread cards. Use `/acknowledge` only for the separate
Learning Support act, which records the professional and timestamp. Personal seen
does not close the concern or produce a support acknowledgement.

Jira checked on 19 October: SCRUM-252 = Testing, SCRUM-244 = Testing, SCRUM-253 = Done.
Testing is intentional pending acceptance; they are not all still Idea.

### API host, migrations and reviewer names

Use `https://api.nevolearning.com` as the canonical configured API host. No promise
is made about the life of an old Render hostname or the cause of its suspension.

Live `/health` checked on 19 October returned `schema: up_to_date`, with both
`schemaExpected` and `schemaApplied` equal to `20261019_0108`. Migration 0105 is
included. The 0104-final note is obsolete. Provider `configured`/`unknown` fields
do not prove successful image/audio generation.

This follow-up adds nullable `reviewedByName` alongside `reviewedBy` in staff depth
variant reads. It is resolved from the same-school account in one query, not trusted
from generated text; absent/deleted reviewers have null rather than invented names.
The student receives no reviewer name. No database migration is needed for this field.

### Affective contract

Accepted: raw touch stays on the device, and anxiety is retired for v1. Do not add
anxiety back through AKT or send raw touch to the proposed ML service. The frontend
owns verification of productive-confusion grace and action wiring; this backend
report does not mark those browser checks passed.

### Test account and CI

Use the dedicated E2E teacher/student rather than the absent old demo.teacher
account. Credentials belong in the secure team handoff/CI secrets, not this committed
document. The E2E-only onboarding fixture records a clear seeded marker and no
invented subject placements. Its live status is verified separately below; do not
apply that fixture shortcut to real children.

## 10. Completion criteria and explicit remaining work

The demo does not wait for AKT: it uses shipped deterministic safeguards and local
BKT. The AKT workstream is complete only when eligible data, reproducible training,
an evaluated compatible checkpoint, private inference, safe fallback, consent checks,
model provenance, shadow evidence and an approved promotion policy all exist.

Still outside a code-only closure: teacher approval of content, approved curriculum
links, psychometric validation, frontend/browser integration, media provider quota
and evidence of educational effectiveness. This document is not a claim that the
whole learning-science paper has been validated.

## 11. Verification performed for this handoff

- Live health: expected/applied schema both 0108, up to date.
- Live E2E teacher and student sign-in: 200. Teacher dashboard, own-student
  profile, adaptation history and unread flags read: 200.
- Live E2E student dashboard and onboarding read: 200, `complete: true`,
  `nextModule: null`. The narrow fixture script reported already complete;
  no fabricated probe placements were added.
- 28 targeted FastAPI/disposable-PostgreSQL runtime tests passed, including
  calculation/scaffold progression, onboarding, reviews and reviewer-name delivery.
- Reviewer-name field is implemented and locally tested in this follow-up; it
  still needs deployment before the frontend can rely on it in production.
- Jira statuses above were read live. Testing was not converted into Done without
  frontend acceptance. No frontend files were changed.
