# SCRUM-21: Centralized Claude gateway

## Derived acceptance contract

The Jira ticket contains a feature description but no explicit acceptance
criteria. This implementation treats the following as the testable contract:

1. Application code has one `AiGatewayService` entry point and one Claude
   provider adapter. Gemini remains a legacy provider option only.
2. Prompts are database-backed, versioned, and restricted to one active version
   per prompt name.
3. Gateway requests are queued by service priority for the remaining model
   backed flows.
4. Concurrency and requests per minute are configurable.
5. Provider output containing prohibited Zero-Tag terminology is rejected and
   regenerated at most the configured number of times.
6. Provider outage, malformed output, or repeated policy rejection returns a
   non-empty deterministic fallback grounded in the supplied source.
7. A call record captures service, prompt version, provider/model, token usage,
   latency, configured cost estimate, school, student, retry count, and safe
   outcome code.
8. Raw prompts, source material, and generated output are not persisted in AI
   telemetry.
9. A supplied student must belong to the authenticated requester's school.
10. Claude credentials are never sent in a query string or returned by the API.
11. Claude Haiku 4.5 (`claude-haiku-4-5`) is the default production model.
12. Claude Sonnet (`claude-sonnet`) is an explicit step-up only for lesson
    transformation quality testing. Opus is not a production default.
13. Prompt caching is enabled for Claude calls by default.
14. Mastery, affective inference, spaced repetition, UDL accommodation, break
    logic, and adaptation stay local and do not call the gateway.

## Initial prompt templates

- `adaptation.default` uses `source_text` and `instruction`.
- `lesson_generation.default` uses `source_text` and `learning_goal`.
- `narrative.default` uses `evidence`.

The lesson and narrative prompts explicitly make teacher material or supplied
evidence the only factual authority.

## Deployment configuration

- `AI_PROVIDER=claude`
- `AI_ANTHROPIC_API_KEY`
- `AI_ANTHROPIC_MODEL=claude-haiku-4-5`
- `AI_ANTHROPIC_SONNET_MODEL=claude-sonnet`
- `AI_PROMPT_CACHING_ENABLED=true`
- `AI_REQUESTS_PER_MINUTE`
- `AI_MAX_CONCURRENCY`
- `AI_INPUT_COST_USD_PER_MILLION`
- `AI_OUTPUT_COST_USD_PER_MILLION`
- `AI_CACHE_WRITE_COST_USD_PER_MILLION`
- `AI_CACHE_READ_COST_USD_PER_MILLION`

The cost rates must match the selected model and deployment tier. Haiku defaults
are `$1/M` input, `$5/M` output, `$1.25/M` cache writes, and `$0.10/M` cache
reads.
