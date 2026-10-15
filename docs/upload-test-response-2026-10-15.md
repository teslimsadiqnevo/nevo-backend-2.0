# Upload test fixes, 15 October 2026

## Educational character names

The roster-name privacy guard could match a fictional lesson character, then
save the provider's pseudonym as teaching content. Parse and parse-time depth
rewrite requests now use request-local character aliases for names found in
their educational source. The provider still receives masked names; only the
exact source characters are restored locally before the generated material is
returned for storage. Emails, contacts, credentials and explicitly labelled
identities are stripped before alias creation and cannot be restored this way.

This is not a blanket PII-detection guarantee for arbitrary uploads. The guard
still uses known school context and identifier patterns; teachers remain
responsible for uploading teaching material rather than personal records.
Chat, student context and export evidence do not receive this restoration.
The temporary alias map is neither logged nor persisted.

## Interactive activities

Valid activity steps no longer disappear just because their completion sentence
is absent; a neutral completion sentence fills that metadata field. Explicit
procedural source text can also be recovered as an activity without inventing
instructions, materials or scientific results. Every source sentence is kept,
with an explicit safety warning placed first. Oversized source instructions are
refused rather than truncated. Explanatory prose and question-only payloads are
not converted into pretend activities, so genuine missing-activity flags remain.

The targeted repair script restores the reported Ada substitution in lesson
`df63fc69` and the source experiment in `319f2cd2`, only in the E2E school.
It defaults to dry run; `--apply` commits. The recovered experiment needs teacher
approval, and image/audio failures remain visible rather than being cleared.

## YarnGPT

The adapter now uses the current v1 TTS request contract: `output_format`, an
idempotency key, queued-job polling and downloading actual audio before storage.
The default host is `api.yarngpt.ai`; an explicit environment override still wins.
The adapter resolves the current voice catalogue and explicitly sends a valid
voice ID, using its default when no configured ID is usable; the live API
requires this even though its documentation describes the field as optional.

Concurrent audio work is serialized per API-key fingerprint within each worker.
Transient errors get bounded retries, short 429 windows honour `Retry-After`,
and long windows fail promptly with a retry delay while suppressing more requests
on that worker. This is not a distributed account-wide scheduler across workers
or other applications using the same provider account, and cannot lift a provider
quota. Cached Supabase audio remains reusable during a provider cooldown.

YarnGPT documents account-wide rate limits, separate from credit balance, and
says top-ups do not increase them:
https://yarngpt.ai/api-docs#rate-limits

## OpenAI image credits

The reported `credit_balance_exhausted` remains a provider-account blocker.
Lydia owns the top-up; these changes do not add credits or claim image generation
has recovered. Failed media must be retried/reprocessed after provider recovery.

## Verification

The targeted repair was applied to the configured E2E school: two stored fields
were corrected in `df63fc69`, and one source activity was recovered in `319f2cd2`.
No unrelated school or learner records were changed.

Focused tests cover source-name restoration versus chat privacy, preservation of
real procedural instructions and safety text, missing outcome metadata, 429
backoff/cooldown sharing and queued-job audio downloads. Live provider generation
is not claimed while the reported rate/credit limits remain unresolved.
The final focused run passed 46 tests, and lint passed.
