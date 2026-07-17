# SCRUM-26: Adaptation engine API

## Scope

Build `/api/intelligence/adapt` for lesson-load adaptation and in-lesson
adjustment decisions. The endpoint consumes parsed content segments, retrieves
the student's learner profile, and returns ordered segment adaptation, proactive
adjustments, break suggestions, and modality suggestions.

## Acceptance criteria

1. Lesson-load requests use the Gemini Gateway with rule-based fallback.
2. In-lesson requests use fast rule-based decisions and do not wait on Gemini.
3. Four independent channel dimensions drive segment prioritisation and
   modality assignment.
4. Multi-channel profiles layer preferences instead of collapsing to one
   channel.
5. Undetermined profiles use balanced defaults.
6. Modality suggestions require all three signals: comprehension decline,
   engagement decline, and a higher-confidence available channel.
7. Frequency constraints block same-segment, consecutive-segment, and repeated
   declined-session suggestions.

## Notes

Parsed lesson segments are request payloads for now. When SCRUM-29 lands the
same service can swap to a repository lookup without changing the response
shape.
