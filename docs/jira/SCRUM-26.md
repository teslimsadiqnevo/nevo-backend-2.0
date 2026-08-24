# SCRUM-26: Adaptation engine API

## Scope

Build `/api/intelligence/adapt` for lesson-load adaptation and in-lesson
adjustment decisions. The endpoint consumes parsed content segments, retrieves
the student's learner profile, and returns ordered segment adaptation, proactive
adjustments, break suggestions, and modality suggestions.

## Acceptance criteria

1. Lesson-load requests use local rule-based adaptation.
2. In-lesson requests use fast rule-based decisions and do not wait on an AI provider.
3. Four independent channel dimensions drive segment prioritisation and
   modality assignment.
4. Multi-channel profiles layer preferences instead of collapsing to one
   channel.
5. Undetermined profiles use balanced defaults.
6. Modality suggestions require all three signals: comprehension decline,
   engagement decline, and a higher-confidence available channel.
7. Frequency constraints block same-segment, consecutive-segment, and repeated
   declined-session suggestions.
8. Raw touch signals never surface through adaptation requests, responses, logs,
   or admin/teacher views. In-lesson adaptation can consume derived,
   session-scoped affective state and multi-signal confirmation only.

## Notes

Parsed lesson segments are request payloads for now. When SCRUM-29 lands the
same service can swap to a repository lookup without changing the response
shape.

Any logged adaptation event must describe the aligned trigger evidence in
functional language and include confidence scores for the decision. Raw touch
signals are IndexedDB-only, deleted at session end, never persisted, and never
rendered as a visible label. The corrected handoff field for dwell is
`interaction_dwell_time`; tablet flows must not fabricate cursor-specific
signals.

The AI model routing ticket supersedes the earlier lesson-load Gemini wording:
adaptation is part of the local intelligence layer and must not call the model
API.
