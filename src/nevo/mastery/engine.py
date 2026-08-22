from uuid import UUID

from nevo.domain.mastery.vocabulary import FailureAttribution
from nevo.mastery.entities import (
    BaselineMasterySeed,
    MasteryState,
    MasteryUpdate,
    MasteryUpdateResult,
)

DEFAULT_GUESS_PROBABILITY = 0.2
DEFAULT_SLIP_PROBABILITY = 0.1
BASELINE_CONCEPT_CAP = 0.7
TEXT_HEAVY_THRESHOLD = 0.65
LOW_READING_THRESHOLD = 0.45
BORDERLINE_READING_THRESHOLD = 0.6
CONCEPT_LEARNING_RATE = 0.16
READING_LEARNING_RATE = 0.10
NEGATIVE_CONCEPT_RATE = 0.12
NEGATIVE_READING_RATE = 0.12
TRANSFER_RATE = 0.08
ATTENTION_LEARNING_RATE = 0.04


class HybridAktMasteryEngine:
    """Pragmatic v1 Hybrid AKT with separate concept and reading tracks.

    This is not the deferred transformer DKT. It keeps the AKT properties the
    ticket needs now: attention-weighted inter-skill transfer, exponential
    updates, and decoupled reading attribution for text-heavy items.
    """

    def initial_state(
        self,
        *,
        student_id: UUID,
        concept_id: UUID,
        seed: BaselineMasterySeed,
        related_concept_ids: tuple[UUID, ...] = (),
    ) -> MasteryState:
        attention_weights = _uniform_attention(related_concept_ids)
        return MasteryState(
            student_id=student_id,
            concept_id=concept_id,
            mastery_probability_concept=_clamp(
                min(seed.concept_probability, BASELINE_CONCEPT_CAP)
            ),
            mastery_probability_reading=_clamp(seed.reading_probability),
            attention_weights=attention_weights,
            guess_probability=DEFAULT_GUESS_PROBABILITY,
            slip_probability=DEFAULT_SLIP_PROBABILITY,
            practice_count=0,
            last_response_correct=None,
            last_failure_attribution=FailureAttribution.NONE,
            seeding_source=seed.source,
        )

    def update(
        self,
        *,
        state: MasteryState,
        interaction: MasteryUpdate,
        related_mastery: dict[UUID, float],
    ) -> MasteryUpdateResult:
        transfer = _attention_transfer(state.attention_weights, related_mastery)
        concept = _clamp(
            state.mastery_probability_concept
            + (1 - state.mastery_probability_concept) * transfer * TRANSFER_RATE
        )
        reading = state.mastery_probability_reading
        attribution = FailureAttribution.NONE
        modality_shift = False

        if interaction.response_correct:
            likelihood = max(0.01, 1 - state.slip_probability)
            concept = _exponential_increase(
                concept,
                CONCEPT_LEARNING_RATE * likelihood,
            )
            if interaction.item_text_density >= TEXT_HEAVY_THRESHOLD:
                reading = _exponential_increase(reading, READING_LEARNING_RATE)
        else:
            attribution = self._failure_attribution(
                reading_probability=reading,
                item_text_density=interaction.item_text_density,
            )
            modality_shift = attribution in {
                FailureAttribution.READING,
                FailureAttribution.MIXED,
            }
            if attribution is FailureAttribution.READING:
                reading = _exponential_decrease(
                    reading,
                    NEGATIVE_READING_RATE * interaction.item_text_density,
                )
            elif attribution is FailureAttribution.CONCEPT:
                concept = _exponential_decrease(concept, NEGATIVE_CONCEPT_RATE)
            else:
                reading_weight = interaction.item_text_density
                concept_weight = 1 - reading_weight
                reading = _exponential_decrease(
                    reading,
                    NEGATIVE_READING_RATE * reading_weight,
                )
                concept = _exponential_decrease(
                    concept,
                    NEGATIVE_CONCEPT_RATE * concept_weight,
                )

        attention_weights = _updated_attention_weights(
            current=state.attention_weights,
            related_mastery=related_mastery,
            response_correct=interaction.response_correct,
        )
        new_state = MasteryState(
            student_id=state.student_id,
            concept_id=state.concept_id,
            mastery_probability_concept=_clamp(concept),
            mastery_probability_reading=_clamp(reading),
            attention_weights=attention_weights,
            guess_probability=state.guess_probability,
            slip_probability=state.slip_probability,
            practice_count=state.practice_count + 1,
            last_response_correct=interaction.response_correct,
            last_failure_attribution=attribution,
            seeding_source=state.seeding_source,
        )
        return MasteryUpdateResult(
            state=new_state,
            attention_transfer=round(transfer, 6),
            recommended_modality_shift=modality_shift,
        )

    def _failure_attribution(
        self,
        *,
        reading_probability: float,
        item_text_density: float,
    ) -> FailureAttribution:
        if (
            reading_probability < LOW_READING_THRESHOLD
            and item_text_density >= TEXT_HEAVY_THRESHOLD
        ):
            return FailureAttribution.READING
        if (
            reading_probability < BORDERLINE_READING_THRESHOLD
            and item_text_density >= 0.45
        ):
            return FailureAttribution.MIXED
        return FailureAttribution.CONCEPT


def concept_seed_from_theta(theta_domain: float | None) -> float:
    if theta_domain is None:
        return 0.15
    normalized = _clamp((theta_domain + 3) / 6)
    return min(BASELINE_CONCEPT_CAP, 0.05 + normalized * 0.55)


def reading_seed_from_wpm(reading_wpm: float | None, *, age_band: str | None) -> float:
    if reading_wpm is None:
        return 0.5
    expected = _expected_wpm(age_band)
    return _clamp(reading_wpm / expected)


def _expected_wpm(age_band: str | None) -> float:
    match age_band:
        case "early_primary":
            return 70
        case "upper_primary":
            return 110
        case "junior_secondary":
            return 140
        case "senior_secondary":
            return 165
        case _:
            return 120


def _uniform_attention(related_concept_ids: tuple[UUID, ...]) -> dict[str, float]:
    if not related_concept_ids:
        return {}
    weight = 1 / len(related_concept_ids)
    return {str(concept_id): weight for concept_id in related_concept_ids}


def _attention_transfer(
    attention_weights: dict[str, float],
    related_mastery: dict[UUID, float],
) -> float:
    if not attention_weights or not related_mastery:
        return 0
    transfer = 0.0
    for concept_id, mastery in related_mastery.items():
        transfer += attention_weights.get(str(concept_id), 0) * mastery
    return _clamp(transfer)


def _updated_attention_weights(
    *,
    current: dict[str, float],
    related_mastery: dict[UUID, float],
    response_correct: bool,
) -> dict[str, float]:
    if not current and related_mastery:
        current = _uniform_attention(tuple(related_mastery))
    if not current:
        return {}
    updated: dict[str, float] = {}
    direction = 1 if response_correct else -1
    for concept_id, weight in current.items():
        mastery = related_mastery.get(UUID(concept_id), 0.5)
        updated[concept_id] = max(
            0.001,
            weight + direction * ATTENTION_LEARNING_RATE * (mastery - 0.5),
        )
    total = sum(updated.values())
    return {key: value / total for key, value in updated.items()}


def _exponential_increase(probability: float, rate: float) -> float:
    return probability + (1 - probability) * rate


def _exponential_decrease(probability: float, rate: float) -> float:
    return probability * (1 - rate)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
