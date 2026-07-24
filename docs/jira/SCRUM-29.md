# SCRUM-29 Content Parsing Pipeline

Implemented the backend slice for Gemini-powered lesson parsing.

## Backend Contract

- Added `lessons`, `content_parse_runs`, and `lesson_segments`.
- Added `POST /api/content/parse`.
- The endpoint accepts extracted source text, page text, or import metadata for PDF, Word, PowerPoint, Google Drive, OneDrive, and text sources.
- Large source text is chunked before Gemini calls.
- Gemini output is normalized into ordered lesson segments tagged with:
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

## Calculation Co-Construction

- `lesson_segments.calculation_variant` stores the co-construction payload.
- Calculation steps are validated for prompt and expected input shape.
- Malformed calculation variants fall back to teacher review.
- Each step receives a `narrationAudio` placeholder with a stable TTS contract:
  - `script`
  - `audioUrl`
  - `durationMs`
  - `provider`

## TTS and Storage

Actual audio generation and storage are intentionally placeholder-backed until SCRUM-50 confirms the storage/TTS provider. The stored JSON shape is already ready for frontend playback once `audioUrl` is populated.

## Fallback

If Gemini is unavailable or returns malformed JSON, the service creates deterministic reviewable segments instead of failing the upload flow. These fallback segments are marked `needsReview` for Upload Step 4.
