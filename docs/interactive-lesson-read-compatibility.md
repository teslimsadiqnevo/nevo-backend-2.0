# Interactive lesson read compatibility

Lesson reads accept both stored question variants and new activity variants.
The same typed union is used for the offline package. No database conversion
is needed: existing prompts, options, answer keys, instructions and type names
are preserved rather than turned into invented activities.

New generation follows SCRUM-134: the interactive modality is a tickable
activity with title, materials, steps and outcome. This does not replace
comprehension checkpoints, quick checks or after-lesson assessments with
activities. Those remain questions. Calculation co-construction is unchanged.

Frontend consumers should render `type: activity` with the activity renderer
and retain the historical question renderer for existing question variants.
Both shapes are named in OpenAPI. This change is backend-only.

## Complete SegmentReviewReason catalogue

Suggested teacher-facing wording, not raw tokens:

| Reason | Meaning |
| --- | --- |
| deterministic_parse_used | A fallback parser prepared this section; please check it. |
| fewer_than_two_modalities | Fewer than two delivery versions are available. |
| interactive_activity_missing | The interactive activity could not be prepared. |
| audio_generation_failed | The audio version could not be prepared. |
| calculation_audio_generation_failed | The calculation narration could not be prepared. |
| visual_generation_failed | The visual version could not be prepared. |
| visual_variant_image_generation_failed | The visual version's image could not be prepared. |
| calculation_variant_malformed | The calculation structure needs checking. |
| calculation_variant_missing_answer | The calculation is missing its answer. |
| calculation_variant_too_few_steps | The calculation needs more steps. |
| calculation_step_missing_prompt | A calculation step is missing its question. |
| calculation_step_unknown_input_type | A calculation step uses an unsupported answer format. |
| calculation_step_missing_answer | A calculation step is missing its answer. |
| calculation_step_missing_options | A choice step is missing its options. |
| calculation_variant_missing_manipulative | The calculation is missing its build pieces. |
| calculation_segment_has_no_interactive_delivery | The calculation has no usable interactive version. |
| model_flagged_for_review | Nevo has asked for a teacher to check this section. |

`interactive_activity_missing` now survives response serialization and appears
in the OpenAPI enum. These are preparation/review reasons, not student labels.
