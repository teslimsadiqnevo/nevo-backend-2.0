from types import SimpleNamespace

import pytest

from nevo.ai_gateway.safety import POLICY_VERSION, SafetyBlocked
from nevo.api.lesson_contracts import (
    ComprehensionCheckpoint,
    UnclassifiableQuestionError,
    VisualVariant,
    checkpoint_payloads,
    student_modalities,
)
from nevo.content_parsing.chunks import reading_chunks
from nevo.content_parsing.depth import source_claims
from nevo.intelligence.delivery_preferences import SegmentChoice, save_choice, segment_choice
from nevo.probe.presentation import ordered_options, standalone_question


@pytest.mark.parametrize("key", ["water", ["water"]])
def test_single_key_legacy_multiple_choice_normalizes_on_read(key):
    item = ComprehensionCheckpoint.model_validate(
        {
            "id": "osmosis",
            "prompt": "What moves?",
            "answerType": "multiple_choice",
            "answerKey": key,
            "options": [{"value": "water", "label": "Water"}, {"value": "salt", "label": "Salt"}],
        }
    )
    assert item.answer_type == "single_choice" and item.answer_key == "water"


def test_multi_key_remains_multiple_and_unknown_upload_is_refused():
    question = {
        "prompt": "Select both",
        "answerType": "multiple_choice",
        "answerKey": ["a", "b"],
        "options": ["a", "b", "c"],
    }
    assert (
        checkpoint_payloads([question], segment_key="s", strict=True)[0]["answerType"]
        == "multiple_choice"
    )
    with pytest.raises(UnclassifiableQuestionError):
        checkpoint_payloads([{**question, "answerType": "guess"}], segment_key="s", strict=True)
    with pytest.raises(UnclassifiableQuestionError):
        checkpoint_payloads([{**question, "answerKey": None}], segment_key="s", strict=True)


def test_numbered_steps_keep_marker_with_instruction():
    body = "1. Take a cup.\n2. Pour water.\n5. What happened?"
    assert source_claims(body) == ["1. Take a cup.", "2. Pour water.", "5. What happened?"]
    chunks = reading_chunks("cup", body)
    assert [chunk["text"] for chunk in chunks] == source_claims(body)
    assert all(body[chunk["startOffset"] : chunk["endOffset"]] == chunk["text"] for chunk in chunks)


def test_available_formats_use_real_cleared_payloads_not_declared_list():
    row = SimpleNamespace(
        body="Text",
        content_type="explanatory_text",
        available_modalities=["visual", "audio"],
        audio_variant=None,
        visual_variant={"imageUrl": "https://example.org/a"},
        interactive_variant=None,
        calculation_variant=None,
    )
    assert student_modalities(row) == ["text"]
    row.visual_variant["safetyPolicyVersion"] = POLICY_VERSION
    row.audio_variant = {"audioUrl": "https://example.org/a.mp3"}
    assert student_modalities(row) == ["visual", "audio", "text"]


def test_safety_stamp_survives_renderer_validation():
    item = VisualVariant.model_validate(
        {
            "imageUrl": "https://example.org/a",
            "storagePath": "a",
            "prompt": "a",
            "provider": "test",
            "generatedAt": "now",
            "caption": "a",
            "safetyPolicyVersion": POLICY_VERSION,
        }
    )
    assert item.model_dump(by_alias=True)["safetyPolicyVersion"] == POLICY_VERSION


def test_choice_is_per_segment_and_partial_updates_preserve_other_choices():
    sitting = SimpleNamespace(delivery_state={"engineConfig": {}})
    first, second = SimpleNamespace(id="one"), SimpleNamespace(id="two")
    save_choice(sitting, first, SegmentChoice(modality="audio", slower=True))
    save_choice(sitting, first, SegmentChoice(depth="simplified"))
    assert segment_choice(sitting, first)["modality"] == "audio"
    assert segment_choice(sitting, first)["slower"] is True
    assert segment_choice(sitting, second)["depth"] == "simplified"
    assert segment_choice(sitting, second)["slower"] is True
    assert "modality" not in segment_choice(sitting, second)


def test_option_order_is_stable_and_not_always_first():
    options = [{"value": key, "label": key} for key in "abcd"]
    orders = [ordered_options(options, seed=str(index)) for index in range(100)]
    assert len({next(i for i, o in enumerate(order) if o["value"] == "a") for order in orders}) == 4
    assert ordered_options(options, seed="child") == ordered_options(options, seed="child")
    assert not standalone_question("In the worked example, what happened?")
    assert standalone_question("Which substance moves during osmosis?")


def test_approved_safety_copy():
    assert (
        SafetyBlocked.public_message
        == "Nevo can\u2019t help with this one. Please talk to a trusted adult or your teacher."
    )
