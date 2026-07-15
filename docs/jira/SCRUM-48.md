# SCRUM-48: Attention flags and intervention recommendations

## Scope

Build the attention flag workflow for engagement-decline and sudden-change
patterns, teacher-to-support escalation records, and Gemini-generated
intervention recommendations.

## Acceptance criteria

1. `attention_flags` stores `student_id`, `flag_type`, functional-language
   description, generated timestamp, and acknowledgement fields.
2. `escalations` stores `student_id`, `teacher_id`, `teacher_note`, optional
   linked flag, generated timestamp, and acknowledgement fields.
3. `intervention_recommendations` stores generated actionable text and links
   each recommendation to both the attention flag and the AI Gateway call.
4. Engagement-decline detection identifies two consecutive recent sessions
   below the student's personal baseline.
5. Sudden-change detection identifies the latest session sharply diverging from
   the student's prior engagement pattern.
6. Recommendation generation uses the existing Gemini Gateway with the
   `intervention_recommendation.default` prompt.

## Notes

The detection service is internal for now and is available from
`app.state.attention_flag_detection_service`. Public route shape can be added
when the teacher dashboard workflow is ready.
