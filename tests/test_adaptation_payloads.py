"""An instruction a client cannot carry out is worse than no instruction.

offer_hint arrived with no hint and show_socratic_panel with no questions, and
the only text on the response was `reason` - which is the reasoning frame. A
learner must not be shown why the system thinks they are struggling; that is
the whole point of the no-labels position.
"""

from __future__ import annotations

import pytest

from nevo.api.intelligence import ProactiveAdjustmentResponse
from nevo.api.lesson_contracts import CalculationVariant
from nevo.domain.intelligence.vocabulary import ManipulativeKind, ProactiveAction


def _adjustment(**overrides: object) -> dict[str, object]:
    return {
        "action": ProactiveAction.SIMPLIFY,
        "reason": "Comprehension has dropped below this session's average.",
        "confidence": 0.7,
        "triggerSignals": [],
        **overrides,
    }


def test_the_action_is_typed_rather_than_any_string() -> None:
    with pytest.raises(ValueError):
        ProactiveAdjustmentResponse.model_validate(_adjustment(action="do_something"))


def test_a_hint_action_must_carry_a_hint() -> None:
    with pytest.raises(ValueError, match="no hint text"):
        ProactiveAdjustmentResponse.model_validate(_adjustment(action=ProactiveAction.OFFER_HINT))


def test_the_reason_cannot_stand_in_for_the_hint() -> None:
    # reason is the reasoning frame and must not reach a child.
    body = ProactiveAdjustmentResponse.model_validate(
        _adjustment(action=ProactiveAction.OFFER_HINT, hint="What is 3 lots of 4?")
    )

    assert body.hint == "What is 3 lots of 4?"
    assert body.hint != body.reason


def test_a_socratic_panel_must_carry_questions() -> None:
    with pytest.raises(ValueError, match="no questions"):
        ProactiveAdjustmentResponse.model_validate(
            _adjustment(action=ProactiveAction.SHOW_SOCRATIC_PANEL)
        )


def test_an_ordinary_action_needs_neither() -> None:
    body = ProactiveAdjustmentResponse.model_validate(_adjustment())

    assert body.hint is None
    assert body.guided_questions == []


class TestManipulative:
    def _variant(self, **overrides: object) -> dict[str, object]:
        return {
            "fullEquation": "1/2 + 1/4",
            "answer": "3/4",
            "steps": [],
            "completionStatement": "Three quarters.",
            **overrides,
        }

    def test_a_calculation_can_carry_one(self) -> None:
        variant = CalculationVariant.model_validate(
            self._variant(manipulative={"kind": "fraction_bar", "parts": 12, "rows": 1})
        )

        assert variant.manipulative is not None
        assert variant.manipulative.kind is ManipulativeKind.FRACTION_BAR
        assert variant.manipulative.parts == 12

    def test_typing_alone_needs_none(self) -> None:
        assert CalculationVariant.model_validate(self._variant()).manipulative is None

    def test_a_whole_cut_into_nothing_is_refused(self) -> None:
        with pytest.raises(ValueError):
            CalculationVariant.model_validate(
                self._variant(manipulative={"kind": "fraction_bar", "parts": 0})
            )

    def test_a_shape_with_no_renderer_is_refused(self) -> None:
        with pytest.raises(ValueError):
            CalculationVariant.model_validate(
                self._variant(manipulative={"kind": "abacus", "parts": 10})
            )


def test_a_drag_step_without_a_manipulative_is_refused_by_the_parse() -> None:
    """Which is why drag was being refused on generated content entirely."""
    from nevo.content_parsing.service import _validated_calculation_variant

    steps = [
        {
            "prompt": "Drag four twelfths",
            "expectedInput": "drag",
            "answer": "4/12",
            "options": [{"value": "a", "label": "1/12"}, {"value": "b", "label": "2/12"}],
        },
        {
            "prompt": "Now three more",
            "expectedInput": "drag",
            "answer": "7/12",
            "options": [{"value": "a", "label": "1/12"}, {"value": "b", "label": "2/12"}],
        },
    ]
    variant, review = _validated_calculation_variant(
        {"fullEquation": "1/3 + 1/4", "answer": "7/12", "steps": steps}
    )

    assert variant is None
    assert review == "calculation_variant_missing_manipulative"

    with_pieces, review = _validated_calculation_variant(
        {
            "fullEquation": "1/3 + 1/4",
            "answer": "7/12",
            "steps": steps,
            "manipulative": {"kind": "fraction_bar", "parts": 12, "rows": 1},
        }
    )

    assert review is None
    assert with_pieces["manipulative"]["parts"] == 12
