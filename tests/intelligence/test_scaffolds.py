from uuid import uuid4

from nevo.domain.intelligence.vocabulary import ScaffoldIntensity, ScaffoldOutcome
from nevo.intelligence.entities import ScaffoldProblemAttempt
from nevo.intelligence.scaffolds import ProgressiveScaffoldFadingEngine


def test_three_correct_full_support_problems_fade_to_partial_on_problem_four() -> None:
    engine = ProgressiveScaffoldFadingEngine()
    student_id = uuid4()
    concept_id = uuid4()
    state = engine.initial_state(student_id=student_id, concept_id=concept_id)

    for index in range(3):
        decision = engine.record_attempt(
            state=state,
            attempt=ScaffoldProblemAttempt(
                student_id=student_id,
                concept_id=concept_id,
                problem_id=f"p{index + 1}",
                response_correct=True,
                response_time_ms=2_000 - index * 100,
                expected_response_time_ms=2_000,
                hint_count=0,
            ),
        )
        state = decision.state

    assert decision.previous_intensity is ScaffoldIntensity.FULL_SUPPORT
    assert decision.next_intensity is ScaffoldIntensity.PARTIAL_SUPPORT
    assert decision.level_changed is True
    assert decision.change_reason == "mastery_signals_accumulated"
    assert state.current_intensity is ScaffoldIntensity.PARTIAL_SUPPORT


def test_struggle_after_fade_reengages_support_without_negative_message() -> None:
    engine = ProgressiveScaffoldFadingEngine()
    student_id = uuid4()
    concept_id = uuid4()
    state = engine.initial_state(student_id=student_id, concept_id=concept_id)
    state = state.__class__(
        student_id=student_id,
        concept_id=concept_id,
        current_intensity=ScaffoldIntensity.PARTIAL_SUPPORT,
    )

    decision = engine.record_attempt(
        state=state,
        attempt=ScaffoldProblemAttempt(
            student_id=student_id,
            concept_id=concept_id,
            problem_id="p4",
            response_correct=False,
            hint_count=2,
        ),
    )

    assert decision.outcome is ScaffoldOutcome.STRUGGLED
    assert decision.next_intensity is ScaffoldIntensity.FULL_SUPPORT
    assert decision.change_reason == "support_reengaged"
    assert "fail" not in decision.student_message.casefold()
    assert "wrong" not in decision.student_message.casefold()


def test_more_intense_hint_use_counts_as_struggle_even_when_answer_is_correct() -> None:
    engine = ProgressiveScaffoldFadingEngine()
    student_id = uuid4()
    concept_id = uuid4()
    state = engine.initial_state(student_id=student_id, concept_id=concept_id)
    state = state.__class__(
        student_id=student_id,
        concept_id=concept_id,
        current_intensity=ScaffoldIntensity.HINTS_ONLY,
        last_hint_count=1,
    )

    decision = engine.record_attempt(
        state=state,
        attempt=ScaffoldProblemAttempt(
            student_id=student_id,
            concept_id=concept_id,
            problem_id="p5",
            response_correct=True,
            hint_count=3,
        ),
    )

    assert decision.outcome is ScaffoldOutcome.STRUGGLED
    assert decision.next_intensity is ScaffoldIntensity.PARTIAL_SUPPORT
