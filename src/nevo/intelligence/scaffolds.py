from uuid import UUID

from nevo.domain.intelligence.vocabulary import ScaffoldIntensity, ScaffoldOutcome
from nevo.intelligence.entities import (
    ScaffoldConceptState,
    ScaffoldDecision,
    ScaffoldProblemAttempt,
)

FADE_AFTER_CONSECUTIVE_CORRECT = 3
INTENSITY_ORDER = (
    ScaffoldIntensity.FULL_SUPPORT,
    ScaffoldIntensity.PARTIAL_SUPPORT,
    ScaffoldIntensity.HINTS_ONLY,
    ScaffoldIntensity.INDEPENDENT,
)


class ProgressiveScaffoldFadingEngine:
    def initial_state(
        self,
        *,
        student_id: UUID,
        concept_id: UUID,
    ) -> ScaffoldConceptState:
        return ScaffoldConceptState(
            student_id=student_id,
            concept_id=concept_id,
            current_intensity=ScaffoldIntensity.FULL_SUPPORT,
        )

    def record_attempt(
        self,
        *,
        state: ScaffoldConceptState,
        attempt: ScaffoldProblemAttempt,
    ) -> ScaffoldDecision:
        intensity_used = attempt.scaffold_intensity or state.current_intensity
        outcome = (
            ScaffoldOutcome.CORRECT
            if _mastery_signal_met(state=state, attempt=attempt)
            else ScaffoldOutcome.STRUGGLED
        )

        if outcome is ScaffoldOutcome.CORRECT:
            consecutive_correct = state.consecutive_correct + 1
            response_time_streak = _response_time_streak(state, attempt)
            hint_streak = _hint_streak(state, attempt)
            next_intensity, reason = _fade_if_ready(
                current=intensity_used,
                consecutive_correct=consecutive_correct,
            )
        else:
            consecutive_correct = 0
            response_time_streak = 0
            hint_streak = 0
            next_intensity, reason = _support_if_needed(intensity_used)

        new_state = ScaffoldConceptState(
            student_id=state.student_id,
            concept_id=state.concept_id,
            current_intensity=next_intensity,
            consecutive_correct=(
                0 if next_intensity != intensity_used else consecutive_correct
            ),
            response_time_improvement_streak=response_time_streak,
            reduced_hint_streak=hint_streak,
            last_response_time_ms=attempt.response_time_ms,
            last_hint_count=attempt.hint_count,
        )
        return ScaffoldDecision(
            state=new_state,
            previous_intensity=intensity_used,
            next_intensity=next_intensity,
            outcome=outcome,
            level_changed=next_intensity != intensity_used,
            change_reason=reason,
            student_message=(
                "Support adjusted for the next problem."
                if next_intensity != intensity_used
                else "Support level kept steady for the next problem."
            ),
        )


def _mastery_signal_met(
    *,
    state: ScaffoldConceptState,
    attempt: ScaffoldProblemAttempt,
) -> bool:
    if not attempt.response_correct:
        return False
    if attempt.expected_response_time_ms and attempt.response_time_ms:
        if attempt.response_time_ms > attempt.expected_response_time_ms * 1.5:
            return False
    if state.last_hint_count is not None and attempt.hint_count > state.last_hint_count:
        return False
    return True


def _response_time_streak(
    state: ScaffoldConceptState,
    attempt: ScaffoldProblemAttempt,
) -> int:
    if state.last_response_time_ms is None or attempt.response_time_ms is None:
        return state.response_time_improvement_streak
    if attempt.response_time_ms <= state.last_response_time_ms:
        return state.response_time_improvement_streak + 1
    return 0


def _hint_streak(state: ScaffoldConceptState, attempt: ScaffoldProblemAttempt) -> int:
    if state.last_hint_count is None:
        return state.reduced_hint_streak
    if attempt.hint_count <= state.last_hint_count:
        return state.reduced_hint_streak + 1
    return 0


def _fade_if_ready(
    *,
    current: ScaffoldIntensity,
    consecutive_correct: int,
) -> tuple[ScaffoldIntensity, str | None]:
    if consecutive_correct < FADE_AFTER_CONSECUTIVE_CORRECT:
        return current, None
    index = INTENSITY_ORDER.index(current)
    if index == len(INTENSITY_ORDER) - 1:
        return current, None
    return INTENSITY_ORDER[index + 1], "mastery_signals_accumulated"


def _support_if_needed(
    current: ScaffoldIntensity,
) -> tuple[ScaffoldIntensity, str | None]:
    index = INTENSITY_ORDER.index(current)
    if index == 0:
        return current, None
    return INTENSITY_ORDER[index - 1], "support_reengaged"
