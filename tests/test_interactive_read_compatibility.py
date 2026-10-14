from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from nevo.api.lesson_contracts import (
    InteractiveActivityVariant,
    InteractiveVariant,
    LegacyInteractiveQuestionVariant,
)
from nevo.api.response_models import LessonSegmentResponse, OfflinePackageModalityVariants
from nevo.domain.intelligence.vocabulary import SegmentReviewReason


@pytest.mark.parametrize("kind", ["practice_problem", "question", "single_choice", None])
def test_stored_questions_survive_online_and_offline_reads(kind):
    question = {
        "prompt": "Which force moves the car?",
        "expectedInteraction": "single_choice",
        "options": [{"value": "push", "label": "A push"}],
        "answerKey": "push",
        "instructions": "Choose one answer.",
    }
    if kind is not None:
        question["type"] = kind
    segment = LessonSegmentResponse.model_validate(
        {
            "id": uuid4(),
            "segmentKey": "force",
            "sequenceOrder": 1,
            "contentType": "explanatory_text",
            "title": "Forces",
            "body": "A push can move a car.",
            "availableModalities": ["text", "interactive"],
            "comprehensionCheckpoints": [],
            "interactiveVariant": question,
            "needsReview": True,
            "reviewReasons": ["interactive_activity_missing"],
        }
    )
    assert isinstance(segment.interactive_variant, LegacyInteractiveQuestionVariant)
    output = segment.model_dump(by_alias=True, mode="json")
    assert output["interactiveVariant"]["prompt"] == question["prompt"]
    assert output["interactiveVariant"]["answerKey"] == "push"
    assert output["interactiveVariant"]["options"][0]["value"] == "push"
    assert output["interactiveVariant"]["options"][0]["label"] == "A push"
    assert output["interactiveVariant"]["type"] == (kind or "practice_problem")
    assert output["reviewReasons"] == ["interactive_activity_missing"]
    offline = OfflinePackageModalityVariants(interactive=question)
    assert offline.model_dump(by_alias=True)["interactive"] == output["interactiveVariant"]


def test_new_activities_keep_the_activity_contract():
    variant = TypeAdapter(InteractiveVariant).validate_python(
        {
            "type": "activity",
            "title": "Explore forces",
            "steps": [{"id": "push", "instruction": "Push a toy car."}],
            "outcome": "You observed a push.",
        }
    )
    assert isinstance(variant, InteractiveActivityVariant)
    assert "prompt" not in variant.model_dump()


def test_review_reason_and_both_shapes_are_named_in_schema():
    schema = LessonSegmentResponse.model_json_schema()
    assert "interactive_activity_missing" in schema["$defs"]["SegmentReviewReason"]["enum"]
    assert "LegacyInteractiveQuestionVariant" in schema["$defs"]
    assert "InteractiveActivityVariant" in schema["$defs"]
    assert len(SegmentReviewReason) == 17
