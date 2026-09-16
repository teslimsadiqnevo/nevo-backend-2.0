"""A step has to say what to render, not just which gesture it wants.

expectedInput said selection, numeric, text or drag, and nothing on the step
said what to draw for any of them - no options for a selection, no expected
value for a numeric. The variant's answer is the whole problem's total, so
mapping it onto the last step is wrong at the units: a step inside a fraction
scaffold asks for a numerator, not a total.
"""

from __future__ import annotations

from nevo.api.lesson_contracts import CalculationStep
from nevo.content_parsing.service import _validated_calculation_variant


def _variant(**step_overrides: object) -> dict[str, object]:
    step = {
        "stepId": "step-1",
        "stepNumber": 1,
        "prompt": "Multiply the principal by the rate.",
        "expectedInput": "numeric",
        "answer": 420000,
        "hint": "60000 times 7.",
        "confirmationText": "That is P times R.",
        "equationState": "P × R = 60000 × 7",  # noqa: RUF001
    }
    step.update(step_overrides)
    second = dict(step)
    second.update({"stepId": "step-2", "stepNumber": 2, "answer": 12600})
    return {
        "type": "co_construction",
        "fullEquation": "I = (60000 × 7 × 3) ÷ 100",  # noqa: RUF001
        "answer": "12600",
        "steps": [step, second],
    }


def test_a_numeric_step_carries_its_own_answer() -> None:
    variant, review = _validated_calculation_variant(_variant())

    assert review is None
    assert variant is not None
    assert variant["steps"][0]["answer"] == 420000
    # Not the variant's total: that is the last step's business, not the first.
    assert variant["steps"][0]["answer"] != variant["answer"]


def test_a_number_stays_a_number() -> None:
    # Quoting it would make a client parse it back; a fraction like "3/4"
    # would stop being one if it were coerced the other way.
    variant, _ = _validated_calculation_variant(_variant())
    assert isinstance(variant["steps"][0]["answer"], int)

    fractional, _ = _validated_calculation_variant(_variant(answer="3/4"))
    assert fractional["steps"][0]["answer"] == "3/4"


def test_a_step_with_no_answer_is_refused() -> None:
    # It cannot be marked, and a client has nothing to check against.
    variant, review = _validated_calculation_variant(_variant(answer=None))

    assert variant is None
    assert review == "calculation_step_missing_answer"


def test_a_selection_step_must_offer_something_to_select() -> None:
    variant, review = _validated_calculation_variant(_variant(expectedInput="selection"))

    assert variant is None
    assert review == "calculation_step_missing_options"


def test_a_selection_step_with_options_is_accepted() -> None:
    variant, review = _validated_calculation_variant(
        _variant(
            expectedInput="selection",
            options=[
                {"value": 420000, "label": "420,000"},
                {"value": 42000, "label": "42,000"},
            ],
        )
    )

    assert review is None
    assert variant["steps"][0]["options"] == [
        {"value": 420000, "label": "420,000"},
        {"value": 42000, "label": "42,000"},
    ]


def test_a_typed_step_offers_no_options() -> None:
    # Numeric and text are typed. An empty list is right for those, and only
    # for those.
    variant, _ = _validated_calculation_variant(_variant())
    assert variant["steps"][0]["options"] == []


def test_half_written_options_are_dropped_rather_than_rendered() -> None:
    variant, review = _validated_calculation_variant(
        _variant(
            expectedInput="selection",
            options=[
                {"value": 420000, "label": "420,000"},
                {"value": 42000},
                {"label": "no value"},
                {"value": 4200, "label": "4,200"},
            ],
        )
    )

    assert review is None
    assert len(variant["steps"][0]["options"]) == 2


def test_the_unit_survives_when_the_model_gives_one() -> None:
    variant, _ = _validated_calculation_variant(_variant(unit="naira"))
    assert variant["steps"][0]["unit"] == "naira"


def test_the_contract_accepts_what_the_parse_produces() -> None:
    # The trap this shape exists to avoid: a field on the wire that the parse
    # never fills, or fills in a form the contract rejects.
    variant, _ = _validated_calculation_variant(
        _variant(
            expectedInput="selection",
            unit="naira",
            options=[{"value": 420000, "label": "420,000"}, {"value": 42000, "label": "42,000"}],
        )
    )
    step = CalculationStep.model_validate(variant["steps"][0])
    assert step.answer == 420000
    assert [option.value for option in step.options] == [420000, 42000]
    assert step.unit == "naira"


def test_each_way_of_being_malformed_says_which() -> None:
    """One blanket reason meant a live rejection named a category, not a cause.

    Two co-constructions were refused in a parsed lesson and all anyone could
    read was "calculation_variant_malformed" - which of four checks had fired
    was unknowable without guessing.
    """

    cases = {
        "calculation_variant_too_few_steps": {
            "steps": [{"prompt": "x", "expectedInput": "numeric"}]
        },
        "calculation_step_missing_prompt": {"steps": [
            {"prompt": "", "expectedInput": "numeric", "answer": 1},
            {"prompt": "b", "expectedInput": "numeric", "answer": 2},
        ]},
        "calculation_step_unknown_input_type": {"steps": [
            {"prompt": "a", "expectedInput": "handwriting", "answer": 1},
            {"prompt": "b", "expectedInput": "numeric", "answer": 2},
        ]},
        "calculation_step_missing_answer": {"steps": [
            {"prompt": "a", "expectedInput": "numeric"},
            {"prompt": "b", "expectedInput": "numeric", "answer": 2},
        ]},
    }
    for expected, payload in cases.items():
        variant, review = _validated_calculation_variant({"answer": "5", **payload})
        assert variant is None, expected
        assert review == expected, f"expected {expected}, got {review}"
