"""Machine-readable answers to the calculation/student asks from 13 October."""

from nevo.api.lesson_contracts import CalculationVariant, Manipulative
from nevo.api.probe import ProbeQuestion
from nevo.api.response_models import EngineConfig, OfflinePackage
from nevo.content_parsing.service import _validated_calculation_variant
from nevo.main import app


def _variant() -> dict[str, object]:
    return {
        "fullEquation": "x + 3 = 7",
        "answer": "4",
        "scaffold": {
            "kind": "number_line",
            "parts": 8,
            "rows": 1,
            "marks": [3, 4, 7],
            "labels": ["start", "answer", "finish"],
        },
        "steps": [
            {
                "stepId": "subtract",
                "stepNumber": 1,
                "prompt": "Type x \u2212 3.",
                "expectedInput": "text",
                "answer": "x\u22123",
                "hint": "Undo plus three.",
                "confirmationText": "Three is removed.",
                "visualUpdate": "Move back three.",
                "equationState": "x = 7 \u2212 3",
            },
            {
                "stepId": "result",
                "stepNumber": 2,
                "prompt": "Type the result.",
                "expectedInput": "numeric",
                "answer": 4,
                "hint": "Count back three.",
                "confirmationText": "x is four.",
                "visualUpdate": "Show four.",
                "equationState": "x = 4",
            },
        ],
        "completionStatement": "You solved for x.",
    }


def test_calculation_steps_name_pad_keys_and_addressable_results() -> None:
    payload, reason = _validated_calculation_variant(_variant())
    assert reason is None
    assert payload is not None
    calculation = CalculationVariant.model_validate(payload)
    first = calculation.steps[0]
    assert first.required_characters == ["\u2212"]
    assert first.result_target_id == "subtract-result"
    assert first.equation_tokens[0].hidden_until_accepted is True
    assert any(
        highlight.target == first.result_target_id and highlight.role == "result"
        for highlight in first.highlights
    )


def test_scaffold_elements_have_ids_and_number_line_has_a_start() -> None:
    calculation = CalculationVariant.model_validate(_variant())
    assert calculation.scaffold is not None
    assert calculation.scaffold.start == 0
    assert calculation.scaffold.mark_ids == ["mark-1", "mark-2", "mark-3"]
    assert calculation.scaffold.label_ids == ["label-1", "label-2", "label-3"]
    assert len(calculation.scaffold.piece_ids) == 8
    assert any(
        highlight.target == "mark-2" and highlight.role == "result"
        for highlight in calculation.steps[1].highlights
    )


def test_build_aliases_are_normalised_to_the_manipulative_vocabulary() -> None:
    assert Manipulative.model_validate({"kind": "dots", "parts": 3}).kind == "counters"
    assert Manipulative.model_validate({"kind": "bar", "parts": 4}).kind == "fraction_bar"


def test_engine_defaults_and_offline_recap_are_explicit() -> None:
    config = EngineConfig()
    assert config.support.initial_scaffold_level == "standard"
    package = OfflinePackage(id="00000000-0000-0000-0000-000000000001", title="No recap")
    assert package.model_dump(by_alias=True, mode="json")["recap"] is None


def test_probe_and_entry_error_contracts_are_declared() -> None:
    assert "subject_id" in ProbeQuestion.model_fields
    operation = app.openapi()["paths"]["/api/v1/student-entry/lookup"]["post"]
    assert "404" in operation["responses"]
    message = app.openapi()["paths"]["/api/messages"]["post"]
    assert "409" in message["responses"]
