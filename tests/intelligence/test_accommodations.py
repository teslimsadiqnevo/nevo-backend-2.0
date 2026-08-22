from uuid import uuid4

from nevo.domain.intelligence.vocabulary import AccommodationType
from nevo.intelligence.accommodations import UdlAccommodationInferenceEngine
from nevo.intelligence.entities import BehaviourPatternAggregate


def test_reading_accommodation_requires_three_aligned_signals_over_five_lessons() -> None:
    result = UdlAccommodationInferenceEngine().analyse(
        student_id=uuid4(),
        aggregate=BehaviourPatternAggregate(
            lesson_count=5,
            reading_latency_lessons=5,
            backward_scroll_lessons=5,
            word_pause_lessons=5,
            low_text_completion_lessons=4,
        ),
    )

    assert [signal.accommodation for signal in result.active] == [
        AccommodationType.READING
    ]
    assert result.active[0].frontend_signal == "reading_accommodation_active"


def test_attention_accommodation_does_not_trigger_before_five_lessons() -> None:
    result = UdlAccommodationInferenceEngine().analyse(
        student_id=uuid4(),
        aggregate=BehaviourPatternAggregate(
            lesson_count=4,
            task_switch_lessons=4,
            erratic_navigation_lessons=4,
            focus_drop_lessons=4,
            fragmented_flow_lessons=4,
        ),
    )

    assert result.active == ()


def test_numerical_accommodation_is_maths_only() -> None:
    result = UdlAccommodationInferenceEngine().analyse(
        student_id=uuid4(),
        aggregate=BehaviourPatternAggregate(
            lesson_count=8,
            maths_lesson_count=4,
            calculation_latency_lessons=5,
            numerical_correction_lessons=5,
            repeated_numeric_mistake_lessons=5,
            numeric_hesitation_lessons=5,
        ),
    )

    assert result.active == ()


def test_multiple_accommodations_can_be_active_for_current_session() -> None:
    result = UdlAccommodationInferenceEngine().analyse(
        student_id=uuid4(),
        aggregate=BehaviourPatternAggregate(
            lesson_count=5,
            reading_latency_lessons=5,
            backward_scroll_lessons=5,
            word_pause_lessons=5,
            task_switch_lessons=5,
            erratic_navigation_lessons=5,
            focus_drop_lessons=5,
            maths_lesson_count=5,
            calculation_latency_lessons=5,
            numerical_correction_lessons=5,
            repeated_numeric_mistake_lessons=5,
        ),
    )

    assert [signal.accommodation for signal in result.active] == [
        AccommodationType.READING,
        AccommodationType.ATTENTION,
        AccommodationType.NUMERICAL,
    ]
