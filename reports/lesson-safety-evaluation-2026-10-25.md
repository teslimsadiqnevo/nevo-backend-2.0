# Lesson-only safety evaluation, 25 October 2026

## Scope

This is a provisional engineering set of 20 synthetic lesson passages and image prompts: 12 labelled allow, 8 labelled withhold. It includes the Zobo precaution and fictional-name patterns that previously caused trouble. No child question, Socratic answer, roster entry, uploaded school document, or production transcript is in the set. Lydia must review the labels before this is used for a product or legal decision.

## Current checker baseline

The existing Claude safety checker, with the production policy and lesson phases, was called on all 20 cases. Before the correction below it had 0 false blocks, 1 unsafe miss, and 0 provider errors. The model had correctly labelled the missed credential-collection case `block/privacy_abuse`, but our privacy false-positive override incorrectly changed that verdict to allow. This was a rule bug, not a model classification failure.

The override now recognises explicit directions to collect children's credentials. On the unchanged 20-case set the current checker returned 0 false blocks, 0 unsafe misses, and 0 provider errors. Per-case verdicts and raw model categories are in `lesson-safety-current-2026-10-25.json`.

## Interpretation and next comparison

Twenty synthetic cases cannot estimate field false-positive or miss rates. This result does not show a systemic problem with the current checker, nor establish that it is safe under adversarial or ambiguous material. Expand the labelled set with independently reviewed, de-identified lesson samples and borderline cases before making a provider decision.

The OpenAI comparison is not run: `OPENAI_API_KEY` is absent locally. The evaluator supports `--provider openai` and uses the same case file, but a comparison must wait for a configured key and label review. Even a favourable lesson result does not authorise sending child-typed Ask Nevo or panel content to OpenAI; that requires a separate decision with Oladayo.
