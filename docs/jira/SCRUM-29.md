# SCRUM-29 Content Parsing Pipeline

Implemented the backend slice for Claude-backed lesson parsing.

## Backend Contract

- Added `lessons`, `content_parse_runs`, and `lesson_segments`.
- Added `POST /api/content/parse`.
- The endpoint accepts extracted source text, page text, or import metadata for PDF, Word, PowerPoint, Google Drive, OneDrive, and text sources.
- Large source text is chunked before AI Gateway calls.
- Claude output is normalized into ordered lesson segments tagged with:
  - `contentType`
  - `sequenceOrder`
  - `availableModalities`
  - `comprehensionCheckpoints`
  - modality variant JSON columns
  - `needsReview` and `reviewReasons`

## Modality Tagging

- Non-calculation segments are normalized so text is always available.
- Segments with fewer than two usable modalities are flagged for teacher review.
- Calculation segments are forced to `["interactive", "visual"]` because the co-construction mechanic is the primary learning experience.
- Visual lesson variants use the Week 2 generated-image contract:
  - `type: "ai_generated_image"`
  - `imageUrl`
  - `prompt`
  - `provider`
  - `generatedAt`
  - optional `caption`
- If image generation fails or the AI provider returns an incomplete visual image object, the backend stores `visual_variant = null`, removes `visual` from `availableModalities`, and marks the segment for teacher review with `visual_variant_image_generation_failed`.

## Calculation Co-Construction

- `lesson_segments.calculation_variant` stores the co-construction payload.
- Calculation steps are validated for prompt and expected input shape.
- Malformed calculation variants fall back to teacher review.
- Each step receives a generated `narrationAudio` object with a stable TTS contract:
  - `script`
  - `audioUrl`
  - `durationMs`
  - `provider`

## TTS and Storage

YarnGPT generates MP3 narration for segment audio and co-construction steps.
The backend uploads each result to the configured Supabase Storage bucket and
persists the playable `audioUrl`. Objects use a content-addressed path, so the
same voice and script reuse the existing audio. Provider or upload failures do
not discard the lesson: the segment is marked for teacher review with an audio
generation failure reason.

The current browser playback contract requires a public `lesson-media` bucket.
The Supabase service-role key remains server-only.

## Fallback

If Claude is unavailable or returns malformed JSON, the service creates deterministic reviewable segments instead of failing the upload flow. These fallback segments are marked `needsReview` for Upload Step 4.

## Prompt library

The six staged parsing prompts are seeded in `ai_prompt_templates`:

- `content_parse.lesson_boundaries`
- `content_parse.module_boundaries`
- `content_parse.segment_boundaries`
- `content_parse.module_recap`
- `content_parse.module_preview`
- `content_parse.boundary_confidence`

Haiku is the default model. Sonnet is an explicit step-up only after Haiku
quality testing shows a transformation needs stronger reasoning.
