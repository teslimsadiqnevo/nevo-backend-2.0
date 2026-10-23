import json
from uuid import uuid4

import pytest

from nevo.api.lesson_contracts import UnclassifiableQuestionError, checkpoint_payloads
from nevo.content_parsing.entities import ContentParseRequest
from nevo.content_parsing.service import ContentParsingService
from nevo.domain.intelligence.vocabulary import LessonSourceType
from tests.content_parsing.test_service import FakeGateway, FakeRepository


def test_snake_case_selection_and_choices_are_normalized_before_strict_validation():
    row = checkpoint_payloads(
        [
            {
                "prompt": "Which gas is needed?",
                "answer_type": "selection",
                "answer_key": "oxygen",
                "choices": ["oxygen", "nitrogen"],
            }
        ],
        segment_key="respiration",
        strict=True,
    )[0]
    assert row["answerType"] == "single_choice"
    assert row["answerKey"] == "oxygen"


@pytest.mark.asyncio
@pytest.mark.parametrize("repaired", [True, False, "dropped"])
async def test_malformed_question_gets_one_correction_attempt_and_never_disappears(repaired):
    question = {"prompt": "Which gas is needed?", "answerType": "selection", "answerKey": "oxygen"}
    payload = {
        "segments": [
            {
                "title": "Respiration",
                "body": "Aerobic respiration needs oxygen.",
                "comprehension_checkpoints": [question],
            }
        ]
    }

    class Gateway(FakeGateway):
        async def generate(self, request):
            if self.requests and repaired:
                question["options"] = ["oxygen", "nitrogen"]
                if repaired == "dropped":
                    payload["segments"][0]["comprehension_checkpoints"] = []
            self.text = json.dumps(payload)
            return await super().generate(request)

    gateway = Gateway("")
    repository = FakeRepository()
    service = ContentParsingService(repository=repository, ai_gateway=gateway)
    request = ContentParseRequest(
        title="Respiration",
        source_type=LessonSourceType.TEXT,
        source_text="Aerobic respiration needs oxygen.",
    )
    if repaired is True:
        result = await service.parse(request=request, requested_by_user_id=uuid4())
        assert result.segments[0].comprehension_checkpoints[0]["answerType"] == "single_choice"
        assert len(result.segments[0].comprehension_checkpoints) == 1
    else:
        with pytest.raises(UnclassifiableQuestionError):
            await service.parse(request=request, requested_by_user_id=uuid4())
        assert repository.parsed is None
    assert len(gateway.requests) == 2
    assert (
        "previous output failed question validation" in gateway.requests[1].variables["source_text"]
    )
