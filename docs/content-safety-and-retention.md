# Backend safety and retention correction

Implementation date: 20 October 2026. Main branch only; the lesson-review redesign remains separate.

## Content safety

- A mandatory server-side safety reviewer checks model inputs, each model/tool-loop output, and the final answer. Ask Nevo, lesson parsing, rewrite generation and other Gateway consumers share this enforcement.
- Illustrations have a prompt check, the existing educational-accuracy review, and an additional image-content safety review before upload. Cached images are checked again before delivery.
- The policy covers exploitation, grooming, explicit sexual content, self-harm, serious violence, targeted hate, dangerous instructions and abuse of personal information. Age-appropriate educational discussion is distinguished from harmful instructions.
- A blocked or safeguarding decision withholds the generated material. Missing configuration, invalid verdicts, provider errors and required audit-write failures fail closed. Ask Nevo returns `403 content_safety_blocked` or `503 safety_check_unavailable`; neither is a successful answer.
- Decisions store category, phase, policy/model version, token usage and scoped identity references, not question text, response text or image bytes. This is separate from existing chat-history storage, which this change does not describe as zero-knowledge or transcript-free.
- Only the school's `senco_admin` can list and acknowledge blocked/safeguarding decisions through `GET /api/v1/safety/events` and `POST /api/v1/safety/events/{id}/acknowledge`. Acknowledgement is idempotent. This queue is not an emergency-response service and does not automatically notify external authorities.
- Historical rewrites without this policy's safety stamp are withheld from student and offline reads until they pass the safety check through teacher approval. Historical unreviewed generated pictures are likewise withheld from new student/offline responses; regeneration runs the new checks. Existing downloaded copies and previously public URLs cannot be recalled by this API change.
- Model-based classification reduces risk; it is not a guarantee that every harmful request or image will be recognised. Teacher review and safeguarding procedures remain necessary.

The reviewer uses the existing `AI_ANTHROPIC_API_KEY`, base URL, API version and default model. No additional vendor key is required. Safety calls add latency and token costs; usage is recorded in `content_safety_events`, separately from generation-call cost estimates.

## Retention

- Migration `20261020_0110` adds purpose-ended, due and purged timestamps. The default is 180 days after purpose cessation, earlier than six calendar months; shorter school windows are honoured and longer windows are capped for this calculation.
- Student deactivation, explicit withdrawal of data-processing consent, or `POST /api/v1/students/{id}/retention/end-purpose` starts the clock. The explicit route is SENCo-only and suspends the account. The system does not guess cessation from an expired billing contract.
- Existing deactivated and consent-withdrawn accounts are backfilled from their existing timestamps, including accounts previously anonymised by name only. An already-overdue learner becomes eligible when the new worker runs.
- The hourly worker deletes owned signal rows, lesson sessions/attempts/progress, mastery/scheduling/scaffold records, profiles/history, flags/interventions/escalations, exports/shares, consent/parent links, auth records, notifications and messages, including dependent rows. Shared curriculum content and another learner's owned records are not deleted merely because they share a school or lesson.
- Structured teacher Ask Nevo context references are included. Legacy full-name/email/admission/login references are also searched in school-scoped transcripts and notifications/messages; matching teacher conversations are removed as a whole. This does not establish that arbitrary unstructured mentions, aliases, or identifiers erased by older anonymisation can always be recovered.
- Managed profile images and written-consent objects are deleted from Supabase before database erasure is committed. A failed storage deletion leaves a retry receipt and does not claim completion. Object deletion is idempotent.
- Successful erasure leaves an identity-empty account stub, lifecycle timestamps and a minimal HMAC/counts receipt, not the learner's learning records. This is deletion of covered records, **not a claim of irreversible anonymisation of every historical copy**.
- Database guards prevent child-data writes from recreating records against a purged account. Restoring an account before erasure cancels its deadline only if processing consent has not been withdrawn. Purged records cannot be restored through the normal product route.
- Append-only protection remains in place for signals and profile history; deletion is permitted only for a due learner with an active purge receipt and a transaction-local retention context. Normal updates/deletes remain refused.
- `GET /api/v1/retention/receipts` is a school-scoped SENCo audit read. Retry failures cause the scheduled job to report failure, rather than silently reporting success.

## Deployment and legal boundaries

Apply `alembic upgrade head` before starting the new application. This migration is based on `0108`; `0109` belongs to the held redesign branch and must be rebased before that branch is merged. Production migration and purge execution must be verified after deployment; local tests are not proof of production erasure.

The first scheduled run can permanently remove already-expired historical learner records and managed files. Confirm the applicable school policy and purpose-ended dates before rollout. Storage credentials and the existing auth session pepper must be configured; the pepper also keys receipt digests.

Backups, restored snapshots, hosting/access/error logs, tracing systems, AI-vendor retention, cached public media and files already downloaded by recipients are not erased by this database worker. Operations must configure and verify their retention/deletion separately, and reconcile purge records before a restored backup is served. Counsel should not state that all copies everywhere are deleted within six months on the strength of this worker alone.

No frontend code is changed. A frontend safety/recovery screen and staff review UI can integrate the declared contracts separately.

## Verification

Verified against a disposable local PostgreSQL database, never the production/test URL: migration upgrade/downgrade, actual signal and immutable profile-history erasure, storage-failure retry, learner isolation, late-write refusal, school-scoped SENCo audit endpoints and purpose cessation. Gateway/image tests cover denied inputs, denied outputs, unavailable/malformed checks and cached-image review. A live Claude smoke check allowed a normal educational request and blocked an unsafe request. These are engineering checks, not a claim of perfect moderation accuracy or production deployment.

Focused verification: 266 tests across retention, Gateway, images, Ask Nevo, exports, operations and learning-runtime endpoints, plus 161 content-parsing tests passed. Ruff and whitespace checks passed for changed code.
