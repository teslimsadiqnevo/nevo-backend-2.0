# AI model routing

## Supersedes

This routing decision supersedes older Jira wording that named Gemini as the
default model provider. The older parser prompt ticket still applies, but its
six prompt-library requirements now run through Claude routing.

## Production routing

- Default workhorse: Claude Haiku 4.5, model `claude-haiku-4-5`.
- Step-up: Claude Sonnet, model `claude-sonnet`, requested explicitly only when
  Haiku lesson transformation quality is not good enough.
- Opus: not a production default and not configured by default.

Ask Nevo student and teacher calls use Haiku. Lesson transformation starts on
Haiku. The service supports an explicit per-request model override for Sonnet so
quality tests can step up without silently increasing cost.

## Cost controls

Prompt caching is enabled by default for Claude calls. Cached usage is audited
separately through cache creation and cache read token counts so Product
Intelligence can track actual savings.

Non-urgent bulk transformation work should use the provider batch path once the
bulk upload worker exists. Real-time Ask Nevo and single upload flows stay on
the normal Messages path.

## Local intelligence boundary

The intelligence layer stays local. Mastery, affective inference, spaced
repetition, UDL accommodation, break logic, and adaptation do not call the model
API. This is the core cost guard that keeps per-student spend inside the annual
budget.

## Budget

The planning ceiling remains `$20/student/year`, with target real cost around
`$5-7/student/year`. Haiku pricing keeps the original Gemini-based cost model
intact while prompt caching provides the main repeated-input saving.
