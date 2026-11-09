import json
from uuid import uuid4

import pytest

from nevo.api.lesson_contracts import checkpoint_payloads
from nevo.content_parsing.entities import ContentParseRequest
from nevo.content_parsing.question_repair import PROMPT_NAME as REPAIR_PROMPT
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
@pytest.mark.parametrize("repaired", [True, False])
async def test_a_malformed_question_is_corrected_or_dropped_but_never_sinks_the_lesson(repaired):
    """One unusable question costs that question, not the teacher's upload.

    The repair model is asked for the invalid fields of the questions that
    failed, keyed by repairId - not for the lesson again. The fake here
    answers in that shape, because a fake that answers in some other shape
    tests the give-up path twice over and the repair path not at all, which
    is how this test spent three weeks asserting a contract 859fb02 had
    already replaced.

    Either way the parse returns a lesson. Dropping is safe because an
    unreviewed check is withheld from delivery since SCRUM-307 and a lesson
    carrying one is not assignable, so failing the parse buys no safety and
    costs the teacher everything they uploaded.
    """

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
            if request.prompt_name == REPAIR_PROMPT:
                rows = [
                    {
                        "repairId": "repair-1",
                        **(
                            {
                                "answerType": "single_choice",
                                "answerKey": "oxygen",
                                "options": ["oxygen", "nitrogen"],
                            }
                            if repaired
                            # A correction that is still unmarkable: the
                            # answer names an option that does not exist.
                            else {"answerType": "single_choice", "answerKey": "argon"}
                        ),
                    }
                ]
                self.text = json.dumps({"questions": rows})
            else:
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

    result = await service.parse(request=request, requested_by_user_id=uuid4())

    assert result.segments, "the lesson itself was lost over one question"
    checks = result.segments[0].comprehension_checkpoints
    notes = {note.get("code") for note in result.review_notes}

    if repaired:
        assert len(checks) == 1
        assert checks[0]["answerType"] == "single_choice"
        assert checks[0]["answerKey"] == "oxygen"
        assert "question_unusable" not in notes
        # Asked once, not three times, when the first correction works.
        assert sum(1 for item in gateway.requests if item.prompt_name == REPAIR_PROMPT) == 1
    else:
        assert checks == ()
        assert "question_unusable" in notes
        note = next(item for item in result.review_notes if item["code"] == "question_unusable")
        # The teacher is told which question went and that the rest is intact.
        assert "Which gas is needed?" in note["questions"]
        assert note["textRetained"] is True
        assert sum(1 for item in gateway.requests if item.prompt_name == REPAIR_PROMPT) == 3


@pytest.mark.asyncio
async def test_repair_giving_up_is_not_the_same_as_repair_returning_rubbish():
    """Both ways a question stays broken have to end in a dropped question.

    859fb02 handled only the second. repair_questions is called from inside
    the handler for the error it raises, so when it exhausted its three
    attempts the raise went straight past that handler and killed the upload
    - Pressure.pdf lost three on 8 November, and Osmosis and Density one
    each, all recorded as "Unclassifiable question after three targeted
    corrections".
    """

    question = {"prompt": "Why does an egg float in very salty water?", "answerType": "selection"}
    payload = {
        "segments": [
            {
                "title": "Density",
                "body": "Salt water is denser than fresh water.",
                "comprehension_checkpoints": [question],
            }
        ]
    }

    class GivesUp(FakeGateway):
        async def generate(self, request):
            # Not the shape repair asks for, so every attempt is rejected and
            # repair_questions raises rather than returning something broken.
            broken = request.prompt_name == REPAIR_PROMPT
            self.text = json.dumps({"questions": "not a list"} if broken else payload)
            return await super().generate(request)

    gateway = GivesUp("")
    repository = FakeRepository()
    service = ContentParsingService(repository=repository, ai_gateway=gateway)

    result = await service.parse(
        request=ContentParseRequest(
            title="Density",
            source_type=LessonSourceType.TEXT,
            source_text="Salt water is denser than fresh water.",
        ),
        requested_by_user_id=uuid4(),
    )

    assert result.segments, "repair giving up still sank the whole upload"
    assert result.segments[0].comprehension_checkpoints == ()
    assert "question_unusable" in {note.get("code") for note in result.review_notes}
