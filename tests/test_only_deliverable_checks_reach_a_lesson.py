"""A check the app cannot ask is dropped and the teacher told, not lost.

Heat Transfer had four checks a teacher read and approved; the class saw one.
The other three were valid here, passed review, and were dropped by the app at
delivery with nothing said to anybody - so she believed she had approved four
questions no child was ever asked.

Approved by Lydia on 10 November: drop them with a note. Delivering them
properly is ranked straight after the three levels pieces, and when that lands
this filter narrows to nothing by itself, because widening
APP_DELIVERABLE_ANSWER_TYPES is the whole change.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from nevo.api.lesson_contracts import APP_DELIVERABLE_ANSWER_TYPES, app_can_deliver
from nevo.content_parsing.entities import ParsedLessonSegment
from nevo.content_parsing.service import _drop_undeliverable_checks
from nevo.domain.intelligence.vocabulary import ContentModality, LessonContentType


def _choice(prompt: str = "Which gas is needed?") -> dict:
    return {
        "id": "q-choice",
        "prompt": prompt,
        "answerType": "single_choice",
        "answerKey": "oxygen",
        "options": [
            {"value": "oxygen", "label": "Oxygen"},
            {"value": "nitrogen", "label": "Nitrogen"},
        ],
    }


def _numeric(prompt: str = "What is the density?") -> dict:
    return {"id": "q-numeric", "prompt": prompt, "answerType": "numeric", "answerKey": 2.5}


def _segment(*checks: dict) -> ParsedLessonSegment:
    return ParsedLessonSegment(
        segment_key="s1",
        content_type=LessonContentType.EXPLANATORY_TEXT,
        sequence_order=1,
        title="Heat transfer",
        body="Metal conducts heat.",
        available_modalities=(ContentModality.TEXT,),
        comprehension_checkpoints=tuple(checks),
    )


def test_a_deliverable_check_is_kept() -> None:
    dropped: list[str] = []
    segments, _ = _drop_undeliverable_checks([_segment(_choice())], [], dropped)
    assert len(segments[0].comprehension_checkpoints) == 1
    assert dropped == []


def test_an_undeliverable_check_is_dropped_and_named() -> None:
    dropped: list[str] = []
    segments, _ = _drop_undeliverable_checks([_segment(_numeric())], [], dropped)
    assert segments[0].comprehension_checkpoints == ()
    assert dropped == ["What is the density?"]


def test_the_heat_transfer_shape_keeps_one_of_four() -> None:
    """The case that started this: four approved, one delivered."""
    checks = (
        _choice("Which conducts heat better?"),
        _numeric("How much heat in joules?"),
        {"id": "q3", "prompt": "Explain convection.", "answerType": "text", "answerKey": "any"},
        {"id": "q4", "prompt": "Is metal a conductor?", "answerType": "boolean", "answerKey": True},
    )
    dropped: list[str] = []
    segments, _ = _drop_undeliverable_checks([_segment(*checks)], [], dropped)

    assert len(segments[0].comprehension_checkpoints) == 1
    assert len(dropped) == 3
    assert "Explain convection." in dropped


def test_the_teaching_text_is_never_touched() -> None:
    original = _segment(_numeric())
    segments, _ = _drop_undeliverable_checks([original], [], [])
    assert segments[0].body == original.body
    assert segments[0].title == original.title


def test_end_of_lesson_questions_are_filtered_too() -> None:
    dropped: list[str] = []
    _, assessment = _drop_undeliverable_checks(
        [], [_choice(), _numeric("Final: what is the speed?")], dropped
    )
    assert len(assessment) == 1
    assert dropped == ["Final: what is the speed?"]


def test_a_question_with_no_prompt_is_still_named_somehow() -> None:
    """A note saying "one question was dropped" with no way to find it is no use."""
    dropped: list[str] = []
    _drop_undeliverable_checks(
        [_segment({"id": "q-nameless", "answerType": "numeric", "answerKey": 1})], [], dropped
    )
    assert dropped == ["q-nameless"]


def test_every_segment_survives_even_when_it_loses_all_its_checks() -> None:
    dropped: list[str] = []
    segments, _ = _drop_undeliverable_checks(
        [_segment(_numeric()), _segment(_choice())], [], dropped
    )
    assert len(segments) == 2


@pytest.mark.parametrize(
    "question",
    [
        _numeric(),
        {"id": "a", "prompt": "p", "answerType": "text", "answerKey": "x"},
        {"id": "b", "prompt": "p", "answerType": "boolean", "answerKey": True},
        {
            "id": "c",
            "prompt": "p",
            "answerType": "multiple_choice",
            "answerKey": ["a", "b"],
            "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
        },
        {
            "id": "d",
            "prompt": "p",
            "answerType": "single_choice",
            "answerKey": "a",
            "options": [{"value": "a", "label": "A"}],
        },
    ],
)
def test_what_the_app_cannot_ask_today(question: dict) -> None:
    assert not app_can_deliver(question)


def test_widening_the_set_is_the_whole_change() -> None:
    """When the app learns another type, this filter narrows by itself."""
    assert APP_DELIVERABLE_ANSWER_TYPES == frozenset({"single_choice"})
    widened = _segment(_numeric())
    # Proving the filter reads the set rather than hard-coding the type.
    assert not app_can_deliver(widened.comprehension_checkpoints[0])


@pytest.mark.asyncio
async def test_the_note_a_teacher_actually_receives() -> None:
    """Through a real parse, so what is pinned is the sentence she reads."""
    import json
    from uuid import uuid4

    from nevo.ai_gateway.entities import AiGenerationResult
    from nevo.content_parsing.entities import ContentParseRequest
    from nevo.content_parsing.service import ContentParsingService
    from nevo.domain.ai_gateway.vocabulary import AiProviderName
    from nevo.domain.intelligence.vocabulary import LessonSourceType
    from tests.content_parsing.test_service import FakeRepository

    payload = {
        "segments": [
            {
                "segment_key": "density-1",
                "content_type": "explanation",
                "sequence_order": 1,
                "title": "Density",
                "body": "Density is mass divided by volume.",
                "availableModalities": ["text"],
                "comprehension_checkpoints": [
                    _choice("Which floats?"),
                    _numeric("What is the density of water?"),
                ],
            }
        ]
    }

    class Gateway:
        async def generate(self, request):
            return AiGenerationResult(
                text=json.dumps(payload),
                provider=AiProviderName.CLAUDE,
                model="claude-haiku-4-5",
                prompt_name=request.prompt_name,
                prompt_version=1,
                fallback_used=False,
                compliance_retries=0,
                call_id=uuid4(),
            )

    repository = FakeRepository()
    service = ContentParsingService(repository=repository, ai_gateway=Gateway())
    await service.parse(
        request=ContentParseRequest(
            title="Density",
            source_type=LessonSourceType.PDF,
            source_text="[Page 1]\nDensity is mass divided by volume.",
        ),
        requested_by_user_id=uuid4(),
    )

    note = next(
        item
        for item in repository.parsed.review_notes
        if item.get("reason") == "not_deliverable_by_app"
    )
    message = note["message"]
    assert "What is the density of water?" in note["questions"]
    assert note["questionCount"] == 1
    # Singular, because one question went.
    assert "this question" in message
    assert "The rest of the lesson is unaffected" in message
    # Says it is the app's limitation, not her question's fault.
    assert "Nothing is wrong with the question itself" in message
    assert "multiple-choice" in message
    # And the deliverable one survived.
    assert len(repository.parsed.segments[0].comprehension_checkpoints) == 1


def test_a_frozen_segment_is_replaced_rather_than_mutated() -> None:
    """The entities are frozen dataclasses; mutating one would raise."""
    original = _segment(_numeric())
    segments, _ = _drop_undeliverable_checks([original], [], [])
    assert original.comprehension_checkpoints != ()
    assert segments[0] is not original
    assert segments[0] == replace(original, comprehension_checkpoints=())
