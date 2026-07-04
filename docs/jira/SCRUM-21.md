# SCRUM-21: Centralized Gemini gateway

## Derived acceptance contract

The Jira ticket contains a feature description but no explicit acceptance
criteria. This implementation treats the following as the testable contract:

1. Application code has one `AiGatewayService` entry point and one Gemini
   provider adapter.
2. Prompts are database-backed, versioned, and restricted to one active version
   per prompt name.
3. Adaptation requests are queued ahead of lesson generation, which is queued
   ahead of narrative work.
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
10. Gemini credentials are never sent in a query string or returned by the API.

## Initial prompt templates

- `adaptation.default` uses `source_text` and `instruction`.
- `lesson_generation.default` uses `source_text` and `learning_goal`.
- `narrative.default` uses `evidence`.

The lesson and adaptation prompts explicitly make teacher material the only
factual authority.

## Deployment configuration

- `AI_GEMINI_API_KEY`
- `AI_GEMINI_MODEL`
- `AI_REQUESTS_PER_MINUTE`
- `AI_MAX_CONCURRENCY`
- `AI_INPUT_COST_USD_PER_MILLION`
- `AI_OUTPUT_COST_USD_PER_MILLION`

The two cost rates must match the selected model and deployment tier.
