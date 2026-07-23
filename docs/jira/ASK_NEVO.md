# Ask Nevo backend service

## Scope

Build student and teacher Ask Nevo backend flows using Gemini through the AI
Gateway, dynamic page-aware context, Zero-Tag compliance, and privacy-preserving
interaction logs.

## Acceptance criteria

1. `/api/v1/ask-nevo/` accepts `role`, `currentPage`, `contextIds`, and
   `question`.
2. Student Ask Nevo uses lesson/page context and blocks cross-student access.
3. Teacher Ask Nevo uses page-specific context from supplied IDs when records
   exist: student profile, flags, recent sessions, escalations, class
   assignments, and lesson identifiers.
4. Student and teacher prompts are separate AI Gateway templates.
5. Responses pass Zero-Tag compliance; violating responses are regenerated and
   then sanitized if needed before returning.
6. `ask_nevo_interactions` logs role, page, context IDs, question category,
   Gateway call ID, and helpfulness, but never full question text.
7. `/api/v1/ask-nevo/{interaction_id}/helpfulness` records response helpfulness.

## Notes

Teacher Ask Nevo calls are tracked separately by `role = teacher` in
`ask_nevo_interactions`, linked to the underlying AI Gateway call for product
intelligence cost and usage analysis.
