from uuid import UUID

from nevo.domain.intelligence.vocabulary import AccommodationType
from nevo.intelligence.entities import (
    AccommodationAnalysis,
    AccommodationSignal,
    BehaviourPatternAggregate,
)

MIN_CONFIRMING_LESSONS = 5
MIN_ALIGNED_SIGNALS = 3
ACCOMMODATION_SIGNAL_BY_TYPE = {
    AccommodationType.READING: "reading_accommodation_active",
    AccommodationType.ATTENTION: "attention_accommodation_active",
    AccommodationType.NUMERICAL: "numerical_accommodation_active",
}


class UdlAccommodationInferenceEngine:
    def analyse(
        self,
        *,
        student_id: UUID,
        aggregate: BehaviourPatternAggregate,
    ) -> AccommodationAnalysis:
        active = []
        reading = _reading_evidence(aggregate)
        if _confirmed(aggregate.lesson_count, reading):
            active.append(_signal(AccommodationType.READING, reading, aggregate.lesson_count))

        attention = _attention_evidence(aggregate)
        if _confirmed(aggregate.lesson_count, attention):
            active.append(
                _signal(AccommodationType.ATTENTION, attention, aggregate.lesson_count)
            )

        numerical = _numerical_evidence(aggregate)
        if _confirmed(aggregate.maths_lesson_count, numerical):
            active.append(
                _signal(
                    AccommodationType.NUMERICAL,
                    numerical,
                    aggregate.maths_lesson_count,
                )
            )

        return AccommodationAnalysis(
            student_id=student_id,
            active=tuple(active),
            source="aggregated_behavioural_patterns",
        )


def _confirmed(lesson_count: int, evidence: tuple[str, ...]) -> bool:
    return lesson_count >= MIN_CONFIRMING_LESSONS and len(evidence) >= MIN_ALIGNED_SIGNALS


def _reading_evidence(aggregate: BehaviourPatternAggregate) -> tuple[str, ...]:
    evidence = []
    if aggregate.reading_latency_lessons >= MIN_CONFIRMING_LESSONS:
        evidence.append("high_reading_latency_on_text_heavy_segments")
    if aggregate.backward_scroll_lessons >= MIN_CONFIRMING_LESSONS:
        evidence.append("elevated_backward_scroll_regressions")
    if aggregate.word_pause_lessons >= MIN_CONFIRMING_LESSONS:
        evidence.append("long_pauses_on_words_or_phrases")
    if aggregate.low_text_completion_lessons >= MIN_CONFIRMING_LESSONS:
        evidence.append("low_completion_rate_on_text_heavy_tasks")
    return tuple(evidence)


def _attention_evidence(aggregate: BehaviourPatternAggregate) -> tuple[str, ...]:
    evidence = []
    if aggregate.task_switch_lessons >= MIN_CONFIRMING_LESSONS:
        evidence.append("frequent_task_switching_within_lesson")
    if aggregate.erratic_navigation_lessons >= MIN_CONFIRMING_LESSONS:
        evidence.append("erratic_navigation_patterns")
    if aggregate.focus_drop_lessons >= MIN_CONFIRMING_LESSONS:
        evidence.append("rapid_focus_drops_after_sustained_content")
    if aggregate.fragmented_flow_lessons >= MIN_CONFIRMING_LESSONS:
        evidence.append("fragmented_task_flow")
    return tuple(evidence)


def _numerical_evidence(aggregate: BehaviourPatternAggregate) -> tuple[str, ...]:
    evidence = []
    if aggregate.calculation_latency_lessons >= MIN_CONFIRMING_LESSONS:
        evidence.append("high_calculation_latency")
    if aggregate.numerical_correction_lessons >= MIN_CONFIRMING_LESSONS:
        evidence.append("frequent_input_corrections_on_numerical_fields")
    if aggregate.repeated_numeric_mistake_lessons >= MIN_CONFIRMING_LESSONS:
        evidence.append("repetitive_mistakes_on_similar_numerical_operations")
    if aggregate.numeric_hesitation_lessons >= MIN_CONFIRMING_LESSONS:
        evidence.append("hesitation_before_numerical_answers")
    return tuple(evidence)


def _signal(
    accommodation: AccommodationType,
    evidence: tuple[str, ...],
    lesson_count: int,
) -> AccommodationSignal:
    return AccommodationSignal(
        accommodation=accommodation,
        frontend_signal=ACCOMMODATION_SIGNAL_BY_TYPE[accommodation],
        evidence=evidence,
        lesson_count=lesson_count,
    )
