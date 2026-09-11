"""A lesson's ending: parsed out of the same payload as its segments."""
import json

from nevo.content_parsing.service import (
    _assessment_questions,
    _json_payload,
    _segments_from_payload_list,
)

PAYLOAD = {
    "segments": [
        {
            "content_type": "explanatory_text",
            "sequence_order": 1,
            "title": "Equal parts",
            "body": "A fraction is a part of a whole.",
            "availableModalities": ["text"],
        }
    ],
    "recap": "You worked out how a whole splits into equal parts.",
    "assessment": [
        {
            "conceptName": "Equal parts",
            "prompt": "What does the bottom number tell you?",
            "answerType": "single_choice",
            "options": [
                {"value": "a", "label": "How many parts in total"},
                {"value": "b", "label": "How many parts are shaded"},
            ],
            "answerKey": "a",
            "explanation": "The denominator counts every equal part.",
        }
    ],
}


def test_the_ending_is_read_from_the_same_payload_as_the_segments() -> None:
    payload = _json_payload(json.dumps(PAYLOAD))

    segments = _segments_from_payload_list(payload, sequence_offset=0)
    assessment = _assessment_questions(payload)

    assert len(segments) == 1
    assert payload["recap"].startswith("You worked out")
    assert len(assessment) == 1
    assert assessment[0]["prompt"] == "What does the bottom number tell you?"
    assert assessment[0]["answerKey"] == "a"


def test_closing_questions_come_back_in_checkpoint_shape() -> None:
    """Same shape as a segment checkpoint, so one renderer serves both."""
    question = _assessment_questions(_json_payload(json.dumps(PAYLOAD)))[0]

    assert set(question) >= {
        "id",
        "prompt",
        "answerType",
        "options",
        "answerKey",
        "explanation",
        "position",
    }
    assert question["id"].startswith("lesson-assessment")


def test_a_lesson_with_no_ending_parses_without_one() -> None:
    """An older prompt, or a model that skipped it, must not fail the parse."""
    payload = _json_payload(json.dumps({"segments": PAYLOAD["segments"]}))

    assert _segments_from_payload_list(payload, sequence_offset=0)
    assert _assessment_questions(payload) == []
    assert payload.get("recap") is None


def test_a_payload_with_no_segments_is_a_parse_failure() -> None:
    """It used to be, and the refactor must not quietly accept an empty lesson."""
    import pytest

    with pytest.raises(ValueError):
        _segments_from_payload_list(_json_payload('{"recap": "x"}'), sequence_offset=0)
