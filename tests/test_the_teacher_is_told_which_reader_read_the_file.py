"""A lesson built from the backup reader says so.

The console reads an uploaded file itself and posts the text. When it cannot,
it posts the file and the server reads it with pypdf instead - no layout, no
scanned pages, tables and columns arriving jumbled or not at all. The lesson
is built from worse text and nothing said so, so a thin lesson read as Nevo
doing a bad job rather than as the file not being readable.

Asserted through a real parse, so what is pinned is the note a teacher
receives rather than the lines of code that put it there.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from nevo.ai_gateway.entities import AiGenerationResult
from nevo.content_parsing.entities import ContentParseRequest, ParsedLesson
from nevo.content_parsing.service import ContentParsingService
from nevo.domain.ai_gateway.vocabulary import AiProviderName
from nevo.domain.intelligence.vocabulary import ContentParseStatus, LessonSourceType

CODE = "source_read_by_backup_reader"

SEGMENTS = """
{
  "segments": [
    {
      "segment_key": "food-chains-1",
      "content_type": "explanation",
      "sequence_order": 1,
      "title": "Producers and consumers",
      "body": "A producer makes its own food. A consumer eats other living things.",
      "availableModalities": ["text"]
    }
  ]
}
"""


class FakeGateway:
    async def generate(self, request):
        return AiGenerationResult(
            text=SEGMENTS,
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


async def _parse(**metadata) -> tuple[FakeRepository, object]:
    repository = FakeRepository()
    service = ContentParsingService(repository=repository, ai_gateway=FakeGateway())
    result = await service.parse(
        request=ContentParseRequest(
            title="Food Chains",
            source_type=LessonSourceType.PDF,
            source_text=(
                "[Page 1]\nProducers make their own food. Consumers eat other "
                "living things.\n[Page 2]\n"
            ),
            source_metadata=dict(metadata),
        ),
        requested_by_user_id=uuid4(),
    )
    return repository, result


def _note(parsed: ParsedLesson) -> dict | None:
    return next((note for note in parsed.review_notes if note.get("code") == CODE), None)


@pytest.mark.asyncio
async def test_a_backup_read_tells_the_teacher_which_reader_was_used() -> None:
    repository, _ = await _parse(readByBackupReader=True)

    note = _note(repository.parsed)
    assert note is not None, "a lesson built from the plainer reader did not say so"
    # The console may never have heard of the code, so the note has to carry
    # its own words rather than relying on a lookup table in the frontend.
    assert note["message"]
    assert "scanned" in note["message"]


@pytest.mark.asyncio
async def test_the_note_says_what_the_teacher_can_do_about_it() -> None:
    repository, _ = await _parse(readByBackupReader=True)

    message = _note(repository.parsed)["message"]
    assert "Check the sections against the original" in message
    assert "uploading the text itself" in message


@pytest.mark.asyncio
async def test_a_lesson_the_console_read_carries_no_such_note() -> None:
    for metadata in ({}, {"readByBackupReader": False}):
        repository, _ = await _parse(**metadata)
        assert _note(repository.parsed) is None


@pytest.mark.asyncio
async def test_the_note_puts_the_lesson_in_front_of_a_teacher() -> None:
    """A note nobody is shown is not telling anyone anything."""
    _, result = await _parse(readByBackupReader=True)
    assert result.status is ContentParseStatus.COMPLETED_WITH_REVIEW


@pytest.mark.asyncio
async def test_the_flag_does_not_displace_the_subject_or_other_metadata() -> None:
    repository, _ = await _parse(readByBackupReader=True, subject="Biology")
    assert _note(repository.parsed) is not None
    assert repository.parsed.segments, "the lesson itself still has to parse"


def test_the_worker_decides_from_the_console_s_own_read_not_the_file_type() -> None:
    """A DOCX the server read is a backup read; a PDF the console read is not.

    Kept as a source check because the decision lives inline in the worker's
    claim loop, which needs a database and a leased job to run. It asserts the
    condition rather than the surrounding lines, so it does not break when the
    code around it moves.
    """
    from nevo.content_parsing import upload_worker

    source = upload_worker.__loader__.get_source(upload_worker.__name__)
    assert 'not metadata.get("contentIsExtractedText")' in source
    assert '"readByBackupReader": True' in source


@pytest.mark.asyncio
async def test_a_clean_read_says_nothing_even_though_the_server_read_it() -> None:
    """Every PDF uses this reader, so "it was used" cannot be the trigger.

    Checking the uploads: every PDF since 23 October was read on the server,
    and only .txt files ever arrived as console-extracted text. A note on
    every PDF lesson would be ignored within a day and would take the real
    ones with it. The trigger is a page that gave up no text.
    """
    repository = FakeRepository()
    service = ContentParsingService(repository=repository, ai_gateway=FakeGateway())
    await service.parse(
        request=ContentParseRequest(
            title="Food Chains",
            source_type=LessonSourceType.PDF,
            # Every page has text, so the read went fine.
            source_text="[Page 1]\nProducers make their own food.\n[Page 2]\nA hawk eats a lizard.",
            source_metadata={"readByBackupReader": True},
        ),
        requested_by_user_id=uuid4(),
    )
    assert _note(repository.parsed) is None


@pytest.mark.asyncio
async def test_the_note_names_the_pages_that_gave_up_nothing() -> None:
    repository, _ = await _parse(readByBackupReader=True)
    note = _note(repository.parsed)
    assert note is not None
    assert note["pageNumbers"], "the teacher is not told which pages to check"
