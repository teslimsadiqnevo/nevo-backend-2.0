from copy import deepcopy

from nevo.api.lesson_contracts import ComprehensionCheckpoint, checkpoint_payloads


def test_presentation_order_is_stable_and_not_changed_by_response_validation():
    question = {
        "id": "water",
        "prompt": "Which substance moves?",
        "answerType": "multiple_choice",
        "answerKey": "water",
        "options": [
            {"value": "water", "label": "Water"},
            {"value": "salt", "label": "Salt"},
            {"value": "starch", "label": "Starch"},
        ],
    }
    original = deepcopy(question)
    positions = set()
    for pupil in range(30):
        shown = checkpoint_payloads(
            [question], segment_key="osmosis", strict=True, presentation_seed=str(pupil)
        )[0]
        assert (
            shown
            == checkpoint_payloads(
                [question], segment_key="osmosis", strict=True, presentation_seed=str(pupil)
            )[0]
        )
        assert (
            ComprehensionCheckpoint.model_validate(shown).model_dump(mode="json", by_alias=True)
            == shown
        )
        assert shown["answerType"] == "single_choice"
        assert shown["answerKey"] == "water"
        assert {option["value"]: option["label"] for option in shown["options"]} == {
            "water": "Water",
            "salt": "Salt",
            "starch": "Starch",
        }
        positions.add(
            next(i for i, option in enumerate(shown["options"]) if option["value"] == "water")
        )
    assert positions == {0, 1, 2}
    assert question == original


def test_multi_answer_keys_remain_attached_to_values():
    row = checkpoint_payloads(
        [
            {
                "prompt": "Select both liquids",
                "answerType": "multiple_choice",
                "options": ["Water", "Oil", "Stone"],
                "answerKey": ["Water", "Oil"],
            }
        ],
        segment_key="liquids",
        strict=True,
        presentation_seed="pupil",
    )[0]
    assert row["answerType"] == "multiple_choice"
    assert row["answerKey"] == ["Water", "Oil"]
    assert {option["value"] for option in row["options"]} == {"Water", "Oil", "Stone"}
