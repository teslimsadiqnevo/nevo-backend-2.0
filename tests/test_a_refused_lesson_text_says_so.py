"""A safety stop on Nevo's own lesson text is a state, not a silent fallback.

Food Chains (5815fe01, 9 November) passed the source check and was then
blocked at "output:content_parse.default" for privacy_abuse. The upload fell
back to two plain segments with no questions, and the teacher was told
nothing - so it looked like Nevo had simply done a poor job of her file.

Two separate faults, and both are covered here: the false positive itself,
and the silence.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from nevo.ai_gateway.entities import AiGenerationResult
from nevo.ai_gateway.safety import SafetyBlocked
from nevo.content_parsing.entities import ContentParseRequest, ParsedLesson
from nevo.content_parsing.service import ContentParsingService
from nevo.domain.ai_gateway.vocabulary import AiProviderName
from nevo.domain.intelligence.vocabulary import ContentParseStatus, LessonSourceType

SOURCE = (
    "[Page 1]\nGrass is a producer. A lizard eats the grass. A hawk eats the lizard.\n"
    "Ngozi says only the lizards are affected. Efe says the grass and the hawks are "
    "affected too. Who is right?"
)


class Refuses:
    """The gateway refusing what Nevo generated, as it did for Food Chains."""

    async def generate(self, request):
        raise SafetyBlocked(categories=("privacy_abuse",), phase="output:content_parse.default")


class Works:
    async def generate(self, request):
        return AiGenerationResult(
            text=json.dumps(
                {
                    "segments": [
                        {
                            "segment_key": "fc-1",
                            "content_type": "explanation",
                            "sequence_order": 1,
                            "title": "Producers and consumers",
                            "body": "A producer makes its own food.",
                            "availableModalities": ["text"],
                        }
                    ]
                }
            ),
            provider=AiProviderName.CLAUDE,
            model="claude-haiku-4-5",
            prompt_name=request.prompt_name,
            prompt_version=1,
            fallback_used=False,
            compliance_retries=0,
            call_id=uuid4(),
        )


class FakeRepository:
    def __init__(self) -> None:
        self.parsed: ParsedLesson | None = None

    async def store(self, *, request, parsed, requested_by_user_id, **_):
        self.parsed = parsed
        return type(
            "Stored",
            (),
            {
                "lesson_id": uuid4(),
                "parse_run_id": uuid4(),
                "status": ContentParseStatus.COMPLETED_WITH_REVIEW
                if parsed.review_notes
                else ContentParseStatus.COMPLETED,
                "title": parsed.title,
                "segment_count": len(parsed.segments),
                "review_segment_count": 0,
                "confirmation_summary": parsed.confirmation_summary,
                "review_notes": parsed.review_notes,
                "segments": parsed.segments,
            },
        )()


async def _parse(gateway):
    repository = FakeRepository()
    service = ContentParsingService(repository=repository, ai_gateway=gateway)
    result = await service.parse(
        request=ContentParseRequest(
            title="Food Chains",
            source_type=LessonSourceType.PDF,
            source_text=SOURCE,
        ),
        requested_by_user_id=uuid4(),
    )
    return repository, result


def _note(parsed: ParsedLesson, code: str) -> dict | None:
    return next((item for item in parsed.review_notes if item.get("code") == code), None)


@pytest.mark.asyncio
async def test_a_refused_lesson_text_is_not_reported_as_a_generic_fallback() -> None:
    repository, _ = await _parse(Refuses())

    assert _note(repository.parsed, "lesson_text_blocked_by_safety") is not None
    assert _note(repository.parsed, "ai_parse_fallback") is None, (
        "a safety stop still reads as Nevo having failed at the file"
    )


@pytest.mark.asyncio
async def test_the_teacher_is_told_her_file_was_not_the_problem() -> None:
    repository, _ = await _parse(Refuses())

    message = _note(repository.parsed, "lesson_text_blocked_by_safety")["message"]
    assert "Your file was not the problem" in message
    assert "we will look at the check" in message


@pytest.mark.asyncio
async def test_the_note_names_no_rule_and_no_trigger() -> None:
    repository, _ = await _parse(Refuses())

    note = _note(repository.parsed, "lesson_text_blocked_by_safety")
    written = " ".join(str(value) for value in note.values()).casefold()
    for leak in ("privacy_abuse", "content_parse", "output:"):
        assert leak not in written, f"{leak} reached the teacher"


@pytest.mark.asyncio
async def test_the_teaching_text_still_comes_through() -> None:
    repository, _ = await _parse(Refuses())

    assert repository.parsed.segments
    body = " ".join(segment.body for segment in repository.parsed.segments)
    assert "hawk" in body


@pytest.mark.asyncio
async def test_the_lesson_lands_in_front_of_a_teacher() -> None:
    _, result = await _parse(Refuses())
    assert result.status is ContentParseStatus.COMPLETED_WITH_REVIEW


@pytest.mark.asyncio
async def test_a_normal_parse_carries_no_such_note() -> None:
    repository, _ = await _parse(Works())
    assert _note(repository.parsed, "lesson_text_blocked_by_safety") is None


def test_the_lesson_policy_now_covers_what_nevo_generated() -> None:
    """The false positive itself.

    The lesson policy - ordinary fictional names are not privacy abuse - was
    applied only at lesson_source. Nevo's own output is checked under
    "output:" plus the prompt name, which matched no branch and so got no
    policy at all. That is why the same text passed one check and failed the
    other.
    """
    from nevo.ai_gateway import safety

    source = safety.__loader__.get_source(safety.__name__)
    assert "_is_lesson_material(phase)" in source
    assert "are not privacy abuse" in source

    policy = next(v for v in vars(safety).values() if hasattr(v, "_is_lesson_material"))
    judge = object.__new__(policy)

    # Every phase that carries a lesson's own words, under all three
    # prefixes. Taken from the blocking decisions actually recorded: all 38
    # are privacy_abuse, spread across eleven phases.
    for phase in (
        "lesson_source",
        "lesson_narration",
        "illustration_source",
        "lesson_rewrite",
        "rewrite_approval",
        "input:content_parse.default",
        "output:content_parse.default",
        "final:content_parse.default",
        "output:lesson_depth.default",
        "final:lesson_depth.default",
        "output:content_question_repair.default",
    ):
        assert policy._is_lesson_material(judge, phase), phase

    # And nothing else. A name in Ask Nevo can be a real child a teacher is
    # asking about rather than a character in a question, so widening into it
    # is a ruling, not a guess.
    for phase in (
        "input:ask_nevo.teacher",
        "output:ask_nevo.teacher",
        "image_prompt",
        "image_output",
        "image_cached",
        "source",
    ):
        assert not policy._is_lesson_material(judge, phase), phase


def test_a_rewrite_gets_both_rules_not_just_the_hazard_one() -> None:
    """rewrite_approval safeguarded five times on privacy_abuse.

    It had the hazard policy and not the names policy, because the two were
    written as alternatives. They stack now.
    """
    from nevo.ai_gateway import safety

    policy = next(v for v in vars(safety).values() if hasattr(v, "_is_lesson_material"))
    judge = object.__new__(policy)
    judge._model = "test-model"

    written = policy._payload(judge, "content", "rewrite_approval")["system"]
    assert "are not privacy abuse" in written
    assert "precautionary wording" in written

    plain = policy._payload(judge, "content", "lesson_source")["system"]
    assert "are not privacy abuse" in plain
    assert "precautionary wording" not in plain

    image = policy._payload(judge, "content", "image_prompt")["system"]
    assert "are not privacy abuse" not in image
