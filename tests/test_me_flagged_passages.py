"""Lydia's ruling A: a /me learner's own flagged passage is released and named.

On /me there is no school to review flagged content, and the learner
uploaded their own material off their own syllabus, so it is released to
them with the passage named. Hard refusals hold for everyone. A school
upload takes exactly the path it always has.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from nevo.ai_gateway.safety import SafetyBlocked
from nevo.content_parsing.entities import ContentParseRequest, ParsedLesson
from nevo.content_parsing.service import ContentParsingService
from nevo.domain.intelligence.vocabulary import LessonSourceType
from nevo.me import safety as me_safety
from nevo.notifications.me_copy import hard_refusal_message
from tests.test_a_refused_lesson_text_says_so import FakeRepository

SOURCE = (
    "[Page 1]\nOkonkwo's fame rested on solid personal achievements. He threw "
    "Amalinze the Cat in a fight that the old men agreed was one of the fiercest."
)


class Refuses:
    def __init__(self, *, phase="lesson_source", categories=("violence",), disposition="block"):
        self.error = SafetyBlocked(categories, phase, disposition=disposition)

    async def generate(self, request):
        raise self.error


async def _parse(gateway, *, individual: bool) -> ParsedLesson:
    repository = FakeRepository()
    service = ContentParsingService(repository=repository, ai_gateway=gateway)
    await service.parse(
        request=ContentParseRequest(
            title="Things Fall Apart",
            source_type=LessonSourceType.PDF,
            source_text=SOURCE,
            source_metadata={"meAudience": "individual"} if individual else {},
        ),
        requested_by_user_id=uuid4(),
    )
    return repository.parsed


def _note(parsed, code):
    return next((item for item in parsed.review_notes if item.get("code") == code), None)


@pytest.mark.asyncio
async def test_a_flagged_passage_is_released_to_its_own_learner_and_named() -> None:
    parsed = await _parse(Refuses(), individual=True)

    assert any("Okonkwo" in segment.body for segment in parsed.segments)
    assert all("safety_hold" not in segment.review_reasons for segment in parsed.segments)
    assert all("safety_flagged" in segment.review_reasons for segment in parsed.segments)
    note = _note(parsed, "lesson_text_flagged_released")
    assert note["pageNumbers"] == [1]
    assert note["reasonCategory"] == "violence"


@pytest.mark.asyncio
async def test_a_school_upload_is_held_exactly_as_before() -> None:
    parsed = await _parse(Refuses(), individual=False)

    assert all("safety_hold" in segment.review_reasons for segment in parsed.segments)
    assert all("Okonkwo" not in segment.body for segment in parsed.segments)
    assert _note(parsed, "lesson_text_blocked_by_safety") is not None
    assert _note(parsed, "lesson_text_flagged_released") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("categories", "disposition"),
    [
        (("self_harm",), "block"),
        (("grooming",), "block"),
        (("violence", "dangerous_instructions"), "block"),
        (("hate_abuse",), "safeguard"),
        ((), "block"),
    ],
)
async def test_a_hard_refusal_holds_for_a_learner_too(categories, disposition) -> None:
    parsed = await _parse(
        Refuses(categories=categories, disposition=disposition), individual=True
    )

    assert all("safety_hold" in segment.review_reasons for segment in parsed.segments)
    assert all("Okonkwo" not in segment.body for segment in parsed.segments)
    assert _note(parsed, "lesson_text_refused_hard")["pageNumbers"] == [1]


@pytest.mark.asyncio
async def test_a_self_harm_refusal_carries_lydias_words_with_the_page() -> None:
    parsed = await _parse(Refuses(categories=("self_harm",)), individual=True)

    assert _note(parsed, "lesson_text_refused_hard")["message"] == (
        "Nevo can't teach this one. The passage on page 1 tells a reader to harm "
        "themselves and keep it from an adult, and that isn't something Nevo will teach. "
        "If you think that's wrong, send it to us and we'll look at it."
    )


@pytest.mark.asyncio
async def test_no_message_is_invented_for_a_category_lydia_has_not_written() -> None:
    parsed = await _parse(Refuses(categories=("grooming",)), individual=True)

    assert _note(parsed, "lesson_text_refused_hard")["message"] is None


@pytest.mark.asyncio
async def test_a_refusal_of_nevos_own_output_gives_the_learner_their_text_unnamed() -> None:
    parsed = await _parse(
        Refuses(phase="output:content_parse.default", categories=("privacy_abuse",)),
        individual=True,
    )

    assert any("Okonkwo" in segment.body for segment in parsed.segments)
    assert all(
        "safety_hold" not in segment.review_reasons
        and "safety_flagged" not in segment.review_reasons
        for segment in parsed.segments
    )
    assert _note(parsed, "generated_content_withheld") is not None
    assert _note(parsed, "lesson_text_flagged_released") is None


def test_hard_is_read_from_what_the_checker_already_says() -> None:
    def blocked(categories, phase="lesson_source", disposition="block"):
        return SafetyBlocked(categories, phase, disposition=disposition)

    assert me_safety.treatment(blocked(("violence",))) == "flagged"
    assert me_safety.treatment(blocked(("hate_abuse", "privacy_abuse"))) == "flagged"
    assert me_safety.treatment(blocked(("violence",), disposition="hold")) == "flagged"
    assert me_safety.treatment(blocked(("self_harm",))) == "hard"
    assert me_safety.treatment(blocked(("sexual_content",))) == "hard"
    assert me_safety.treatment(blocked(("violence",), disposition="safeguard")) == "hard"
    assert me_safety.treatment(blocked(())) == "hard"
    assert me_safety.treatment(blocked(("self_harm",), phase="output:x")) == "generated"


def test_the_hard_message_needs_a_page() -> None:
    assert hard_refusal_message(category="self_harm", page=None) is None
