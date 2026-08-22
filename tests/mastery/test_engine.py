from uuid import uuid4

from nevo.domain.mastery.vocabulary import FailureAttribution
from nevo.mastery.engine import HybridAktMasteryEngine
from nevo.mastery.entities import BaselineMasterySeed, MasteryUpdate


def test_text_heavy_failure_with_low_reading_does_not_depress_concept_mastery() -> None:
    engine = HybridAktMasteryEngine()
    student_id = uuid4()
    concept_id = uuid4()
    state = engine.initial_state(
        student_id=student_id,
        concept_id=concept_id,
        seed=BaselineMasterySeed(
            concept_probability=0.5,
            reading_probability=0.25,
            source="test",
        ),
    )

    result = engine.update(
        state=state,
        interaction=MasteryUpdate(
            student_id=student_id,
            concept_id=concept_id,
            response_correct=False,
            item_text_density=0.9,
        ),
        related_mastery={},
    )

    assert result.state.last_failure_attribution is FailureAttribution.READING
    assert result.recommended_modality_shift is True
    assert result.state.mastery_probability_concept == state.mastery_probability_concept
    assert result.state.mastery_probability_reading < state.mastery_probability_reading


def test_visual_failure_with_adequate_reading_updates_concept_mastery_downward() -> None:
    engine = HybridAktMasteryEngine()
    student_id = uuid4()
    concept_id = uuid4()
    state = engine.initial_state(
        student_id=student_id,
        concept_id=concept_id,
        seed=BaselineMasterySeed(
            concept_probability=0.5,
            reading_probability=0.75,
            source="test",
        ),
    )

    result = engine.update(
        state=state,
        interaction=MasteryUpdate(
            student_id=student_id,
            concept_id=concept_id,
            response_correct=False,
            item_text_density=0.15,
        ),
        related_mastery={},
    )

    assert result.state.last_failure_attribution is FailureAttribution.CONCEPT
    assert result.state.mastery_probability_concept < state.mastery_probability_concept
    assert result.state.mastery_probability_reading == state.mastery_probability_reading


def test_attention_transfer_increases_current_concept_after_related_mastery() -> None:
    engine = HybridAktMasteryEngine()
    student_id = uuid4()
    concept_id = uuid4()
    related = uuid4()
    state = engine.initial_state(
        student_id=student_id,
        concept_id=concept_id,
        seed=BaselineMasterySeed(
            concept_probability=0.2,
            reading_probability=0.7,
            source="test",
        ),
        related_concept_ids=(related,),
    )

    result = engine.update(
        state=state,
        interaction=MasteryUpdate(
            student_id=student_id,
            concept_id=concept_id,
            response_correct=True,
            item_text_density=0.1,
            related_concept_ids=(related,),
        ),
        related_mastery={related: 0.9},
    )

    assert result.attention_transfer == 0.9
    assert result.state.mastery_probability_concept > state.mastery_probability_concept
    assert abs(sum(result.state.attention_weights.values()) - 1) < 0.000001


def test_baseline_seed_never_exceeds_ticket_cap() -> None:
    engine = HybridAktMasteryEngine()

    state = engine.initial_state(
        student_id=uuid4(),
        concept_id=uuid4(),
        seed=BaselineMasterySeed(
            concept_probability=0.95,
            reading_probability=0.9,
            source="test",
        ),
    )

    assert state.mastery_probability_concept == 0.7


def test_twenty_mixed_interactions_do_not_false_depress_text_heavy_concept() -> None:
    engine = HybridAktMasteryEngine()
    student_id = uuid4()
    concept_id = uuid4()
    state = engine.initial_state(
        student_id=student_id,
        concept_id=concept_id,
        seed=BaselineMasterySeed(
            concept_probability=0.45,
            reading_probability=0.25,
            source="test",
        ),
    )

    for index in range(20):
        text_heavy = index % 2 == 0
        result = engine.update(
            state=state,
            interaction=MasteryUpdate(
                student_id=student_id,
                concept_id=concept_id,
                response_correct=not text_heavy,
                item_text_density=0.9 if text_heavy else 0.1,
            ),
            related_mastery={},
        )
        state = result.state

    assert state.practice_count == 20
    assert state.mastery_probability_concept > 0.45
    assert state.mastery_probability_reading < 0.25
