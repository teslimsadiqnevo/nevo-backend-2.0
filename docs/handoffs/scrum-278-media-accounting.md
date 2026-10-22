# SCRUM-278: media generation accounting

## Delivered

Backend-only, durable `media_usage_events` ledger, migration `20261022_0112`.
Audio and image adapters automatically meter generation, including repair scripts.
Each run and each actual provider HTTP attempt is persisted before network I/O.
Failures, transport errors, cancellations and interrupted processes are distinguishable.
A process killed after dispatch leaves `started`, not a fabricated success or zero cost.
If accounting is unavailable, new generation fails closed rather than spending unrecorded.

The ledger includes:

- Generation runs, cache hits, successful stored asset paths and failed runs.
- YarnGPT synthesis attempts, retries, voice catalogue reads and job polling separately.
- OpenAI image generation attempts, including regenerated rejected candidates.
- Claude educational image reviews and source/prompt/output/cache safety reviews.
- Provider request IDs/job IDs, status codes, token or character counts, and price snapshots.
- Decimal cost estimates, explicit currency and unknown costs, without currency conversion.

No prompts, scripts, question text, image bytes, headers, credentials, signed URLs,
student identities or learner profiles are stored in this ledger.
Provider request IDs and asset hashes are operational correlation handles only.
Safety review calls already present in AI gateway reports must not be added again to
this report's costs when calculating a combined AI total.

## Reuse and cost interpretation

Media is generated at lesson preparation or explicit repair, not per child/session/serve.
Audio is reused by normalized script plus configured voice. Images are reused by
prompt, model and safety-policy version. Cached images can still incur safety-review costs.
Audio cache lookup truncates the existing narration input to 2,000 characters; this ticket
does not change narration content or introduce per-student audio.

An HTTP success is not necessarily an accepted image or a completed audio job.
The generation-run result records whether media was actually stored. Rejected or failed
generation can still cost money. HTTP errors/timeouts remain unpriced unless separately
reconciled, not assumed free. Repeated YarnGPT job IDs are counted as separate HTTP
attempts but their cost estimate is attributed only to the first priced ledger
entry, including when a replay falls in a later reporting period.

Old calls cannot be reconstructed from old assets. Counting starts at deployment;
the report exposes the first recorded timestamp. Current asset inventory is a count of
database references, not verification that all bucket objects exist. It includes existing
historical assets while call counts apply only to the requested reporting interval.

## Deployment

Run `alembic upgrade head` before using the new media generation adapters.
The normal Render start command already runs migrations before starting the API.
No frontend changes or changes to the lesson payload are required.
The private reporting routes described below require an additional secret, not a school role.

Standard direct-API token prices for the current GPT Image 2, Claude Opus 4.8 and
Claude Haiku 4.5 models are included, checked on 22 October 2026 against the
[OpenAI pricing](https://developers.openai.com/api/docs/pricing) and
[Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) pages.
They are estimates at published standard rates, not a guarantee about account discounts.
No default YarnGPT rate is guessed. Unknown model names remain unpriced.

Set `MEDIA_PRICING_JSON` to add YarnGPT or override whole rate objects with
the contracted rates for the models actually used.
Keys are `provider:model` (e.g. `yarngpt:tts`, `openai:gpt-image-2`,
`anthropic:claude-opus-4-8`, `anthropic:claude-haiku-4-5`). Each rate object requires
an uppercase three-letter `currency`. Supported rate keys:

- `per_1000_characters`: narration estimate based on submitted characters.
- `per_image`: fixed-price image contracts only; do not use a size-blind flat price
  for a token-billed image model.
- `input_per_million`, `output_per_million`: model token prices.
- `input_text_per_million`, `input_image_per_million`: separate image-model input prices.
- `cache_read_per_million`, `cache_write_per_million`: cached token prices.

Missing prices or missing required usage produce NULL cost and an unknown-cost count.
Zero is recorded only when supported by the available usage/rates or for non-generating
catalogue/job reads. Changes to rates do not retrospectively change stored estimates.
Narration prices must come from YarnGPT's billing agreement or itemised charges,
not a guessed conversion from credits to money. Provider invoices remain authoritative;
these are estimates, not
a claim that the provider has billed exactly that amount.

## Operator report

Set `OPS_REPORT_KEY` in Render to a random secret of at least 32 characters.
A generated value is available in this checkout's ignored `.env`; never put it in frontend envs.
Open `/api/ops/media-usage/view` for the readable report and sign in with username
`ops` and that secret as password. `/api/ops/media-usage` returns typed JSON;
API clients can instead send `X-Nevo-Ops-Key`. Both support `from` and `until` dates.
School tokens alone cannot read platform spending. Responses are not cacheable.
These routes use the existing 0112 ledger and need no additional migration.

`POST /api/ops/media-usage/effective-rate` calculates a measured YarnGPT effective
rate from a closed top-up cycle. Supply `from`, `until`, `paidAmount`, `refunds`,
`currency`, and true attestations `fullyConsumed`, `zeroOpeningBalance`,
`exclusiveNarrationUse`, `trackingCoveredWholeCycle`. Uncertain dispatched calls
require reconciliation first. The denominator is deduplicated accepted synthesis
characters, not polling or retry counts. This is an effective observed rate, not
an official tariff; it neither persists nor applies a price automatically.

Verified Osmosis inventory on 22 October: six base narration assets and four base
images, not eighteen narrations. Eligible base media is generated during upload
preparation or explicit repair, not first playback. Simplify/Expand are text rewrites;
Slower does not generate a separate narration. Calculation-step narration, where
authored, is an additional asset tracked separately.

```bash
python scripts/report_media_usage.py \
  --from 2026-10-22T00:00:00+00:00 \
  --until 2026-10-23T00:00:00+00:00
```

Requires trusted database access, not a school admin or student token. Returns JSON
grouped by medium/provider/model/operation: runs, cache hits, calls, retries, failures,
unfinished attempts, unknown-cost calls, currency-separated estimated totals and
current distinct referenced assets. No real paid generation is needed to run it.

## Remaining operational facts

Set any contracted overrides in Render before interpreting monetary totals. YarnGPT's
current account rate is not exposed by its API and the account owner reports it is
not disclosed in the Account UI either. Until the provider supplies a rate or itemised
charges, narration money remains unknown. The report still supplies submitted-character
totals and unique accepted characters (deduplicating job replays) without pretending
those characters are a confirmed billed quantity or converting them into money.
This implementation neither restores historical bills nor configures off-provider backups.
