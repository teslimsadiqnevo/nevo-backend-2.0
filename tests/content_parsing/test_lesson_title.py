"""What a lesson is called in a teacher's library.

The title used to be the uploaded filename with its punctuation swapped for
spaces, so a document whose own heading read "Simple Interest" arrived as
"simple interest jss3". The parser reads the whole source and is the one part
of the pipeline that knows what the lesson is about, so it names it; the
filename is only what we fall back to.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from nevo.ai_gateway.entities import AiGenerationResult
from nevo.api.frontend_unblockers import _title_from_filename
from nevo.content_parsing.entities import ContentParseRequest, ParsedLesson
from nevo.content_parsing.service import (
    MAX_TITLE_CHARS,
    ContentParsingService,
    _lesson_title,
)
from nevo.domain.ai_gateway.vocabulary import AiProviderName
from nevo.domain.intelligence.vocabulary import ContentParseStatus, LessonSourceType


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("simple-interest-jss3.docx", "Simple Interest JSS3"),
        ("photosynthesis_ss2.pdf", "Photosynthesis SS2"),
        ("the water cycle.txt", "The Water Cycle"),
        ("NERDC scheme of work.docx", "NERDC Scheme Of Work"),
        ("lesson.pptx", "Lesson"),
        ("", "Uploaded lesson"),
        (None, "Uploaded lesson"),
    ],
)
def test_a_filename_still_reads_like_a_name(filename: str | None, expected: str) -> None:
    assert _title_from_filename(filename) == expected


def test_the_parsers_title_is_taken_as_written() -> None:
    assert _lesson_title("Simple Interest") == "Simple Interest"


def test_whitespace_is_tidied_but_the_words_are_not() -> None:
    assert _lesson_title("  Simple\n  Interest ") == "Simple Interest"


def test_a_sentence_is_not_a_title() -> None:
    # A model that explains the lesson instead of naming it is no improvement
    # on the filename, so the filename wins.
    assert _lesson_title("x" * (MAX_TITLE_CHARS + 1)) is None


def test_nothing_offered_means_nothing_taken() -> None:
    assert _lesson_title(None) is None
    assert _lesson_title("") is None
    assert _lesson_title("   ") is None


class _Gateway:
    def __init__(self, text: str) -> None:
        self.text = text

    async def generate(self, request: object) -> AiGenerationResult:
        return AiGenerationResult(
            text=self.text,
            provider=AiProviderName.CLAUDE,
            model="claude-haiku-4-5",
            prompt_name=getattr(request, "prompt_name", "content_parse.default"),
            prompt_version=1,
            fallback_used=False,
            compliance_retries=0,
            call_id=uuid4(),
        )


class _Repository:
    def __init__(self) -> None:
        self.parsed: ParsedLesson | None = None

    async def store(self, *, request: object, parsed: ParsedLesson, **_: object) -> object:
        del request
        self.parsed = parsed
        return SimpleNamespace(
            lesson_id=uuid4(),
            parse_run_id=uuid4(),
            status=ContentParseStatus.COMPLETED,
        )


PAYLOAD = json.dumps(
    {
        "title": "Simple Interest",
        "segments": [
            {
                "content_type": "definition",
                "sequence_order": 1,
                "title": "What interest is",
                "body": "Interest is what a bank pays you for leaving money there.",
                "availableModalities": ["text"],
            }
        ],
    }
)


@pytest.mark.asyncio
async def test_the_parser_names_the_lesson_not_the_upload() -> None:
    repository = _Repository()
    service = ContentParsingService(repository=repository, ai_gateway=_Gateway(PAYLOAD))

    await service.parse(
        request=ContentParseRequest(
            title="Simple Interest JSS3",
            source_type=LessonSourceType.WORD,
            source_text="Interest is what a bank pays you for leaving money there.",
        ),
        requested_by_user_id=uuid4(),
    )

    assert repository.parsed is not None
    assert repository.parsed.title == "Simple Interest"


@pytest.mark.asyncio
async def test_the_filename_stands_in_when_the_parser_names_nothing() -> None:
    repository = _Repository()
    payload = json.dumps({"segments": json.loads(PAYLOAD)["segments"]})
    service = ContentParsingService(repository=repository, ai_gateway=_Gateway(payload))

    await service.parse(
        request=ContentParseRequest(
            title="Simple Interest JSS3",
            source_type=LessonSourceType.WORD,
            source_text="Interest is what a bank pays you for leaving money there.",
        ),
        requested_by_user_id=uuid4(),
    )

    assert repository.parsed is not None
    assert repository.parsed.title == "Simple Interest JSS3"
