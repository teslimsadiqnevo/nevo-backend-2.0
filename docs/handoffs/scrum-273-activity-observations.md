# SCRUM-273: authored activity observations

Backend-only change; no migration is required. Deploy the pushed commit for the new public schema and omission behaviour.

- `interactiveVariant.inProgress` is an optional source-authored observation while the child works.
- `interactiveVariant.outcome` is the optional source-authored final observation.
- An absent line is omitted entirely, not returned as null, an empty string or a generic completion sentence. The same rule applies to online and offline payloads.
- New uploads must copy these lines from the uploaded source. After parsing, lines not found in that source (allowing whitespace differences from extraction) are removed. Neither line is inferred from procedural steps.
- Existing activities still load without either field. Legacy completion boilerplate is suppressed on reads and has been removed from seven stored activities. Actual steps are preserved even when there is no outcome.
- Osmosis section 4 was checked against the original Osmosis.pdf bytes retained for upload f797428f. Its final observation is restored verbatim from the source's "What you should see" paragraph. The source has no in-progress observation, so `inProgress` is absent. All six existing activity steps are unchanged.
- 196 parser, compatibility, contract and player regression tests passed, including missing/default omission and rejection of invented observation lines.
