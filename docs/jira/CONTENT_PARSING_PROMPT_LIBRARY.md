# Content parsing prompt library

## Provider

The original prompt-library ticket named Gemini. The active routing decision is
Claude: Haiku first, Sonnet only as an explicit quality step-up for lesson
transformation.

## Versioned prompts

The six parser prompts live in `ai_prompt_templates` and are seeded by migration
`20260824_0027_claude_routing_and_parser_prompts.py`:

- `content_parse.lesson_boundaries`
- `content_parse.module_boundaries`
- `content_parse.segment_boundaries`
- `content_parse.module_recap`
- `content_parse.module_preview`
- `content_parse.boundary_confidence`

All six return strict JSON, use the teacher source as the factual authority, use
Zero-Tag functional language, avoid student ranking, and avoid easy/hard module
framing.

## Output schemas

- Lesson boundaries: `{ "lessons": [{ "title", "start_page", "end_page", "segment_hint_count" }] }`
- Module boundaries: `{ "modules": [{ "title", "segment_indices": [] }] }`
- Segments: `{ "segments": [{ "title", "modality", "content_range" }] }`
- Recap: `{ "recap": "string" }`
- Preview: `{ "preview": "string" }`
- Confidence: `{ "confidence": "high" | "low", "reason": "string" }`

## Testing corpus

The required review corpus remains:

- P5 Science textbook chapter
- JSS2 Mathematics scheme of work
- SS1 English literature unit
- OCR text from handwritten teacher notes
- Short 3-segment lesson
- Long 20-segment block or ceiling-exceeded block

The migration locks the prompt names and schemas. Corpus quality review can now
iterate prompt versions without service redeploy.
