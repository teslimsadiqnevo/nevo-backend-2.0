# ADR 0007: Centralized AI gateway

## Status

Accepted.

## Context

Nevo needs one controlled boundary for Gemini calls. Direct provider calls from
features would make prompt changes, Zero-Tag enforcement, cost attribution,
fallback behavior, and rate-limit handling inconsistent.

## Decision

All application AI generation goes through `AiGatewayService`.

- Prompt templates are stored with immutable integer versions. One version per
  prompt name may be active.
- The REST provider adapter is isolated behind `TextGenerationProvider`.
- An in-process priority scheduler gives live adaptation precedence over lesson
  generation and narrative work while enforcing configured concurrency and RPM.
  The scheduler is behind a port so a shared queue can replace it when Nevo runs
  multiple application replicas.
- Every provider response is checked against the Zero-Tag response policy. A
  rejected response is regenerated at most twice, then a deterministic,
  source-preserving fallback is returned.
- Missing credentials, provider errors, timeouts, malformed responses, and
  exhausted compliance retries never return a blank response.
- Telemetry records school/student attribution, service, prompt version,
  provider/model, tokens, latency, configured cost estimate, retry count, and
  safe error code. Prompt variables and generated text are not stored.
- Gemini credentials are sent in the `x-goog-api-key` header, not the URL.

## Consequences

Feature code depends on a provider-neutral service and cannot bypass policy by
using Gemini directly. Per-project Gemini limits still apply across replicas;
the current process-local scheduler protects each replica and can be replaced by
a distributed implementation without changing callers.

Cost estimates require the deployment to set the input and output price per
million tokens for its selected model. Token usage remains available even when
those rates are zero (for example, a free-tier environment).
