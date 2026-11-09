"""A refused picture costs that section its picture, not the whole upload.

Every other way an image can fail - a dropped connection, a storage error, an
image the educational review rejects - drops the picture, writes a note and
marks the section for review. A safety block was re-raised instead, so one
refused illustration lost the teacher everything they had uploaded.

The block here is about the image prompt or the drawn image. The lesson's own
text is checked once at the top of the parse and still fails the upload if it
is refused, so nothing here weakens the gate that matters.
"""

from __future__ import annotations

import pytest

from nevo.ai_gateway.safety import SafetyBlocked
from nevo.content_parsing.entities import ParsedLessonSegment
from nevo.content_parsing.service import ContentParsingService
from nevo.domain.intelligence.vocabulary import ContentModality, LessonContentType
from nevo.visuals.service import VisualGenerationError


def _segment(**overrides) -> ParsedLessonSegment:
    return ParsedLessonSegment(
        segment_key="food-chains-2",
        content_type=LessonContentType.EXPLANATORY_TEXT,
        sequence_order=2,
        title="A pond food chain",
        body="Grass is eaten by a lizard. The lizard is eaten by a hawk.",
        available_modalities=(ContentModality.TEXT, ContentModality.VISUAL),
        **overrides,
    )


class Refuses:
    """The visuals service refusing one segment's picture."""

    def __init__(self, categories=("privacy_abuse",), phase="image_prompt") -> None:
        self.cause = SafetyBlocked(categories=tuple(categories), phase=phase)
        self.calls = 0

    async def generate(self, **_):
        self.calls += 1
        raise VisualGenerationError(self.cause.public_message) from self.cause


class Breaks:
    """The visuals service failing for an ordinary, non-safety reason."""

    async def generate(self, **_):
        raise VisualGenerationError("Image request failed: ReadTimeout")


async def _illustrate(generator, segment=None):
    service = ContentParsingService(repository=None, ai_gateway=None)
    service._visual_generation = generator
    notes: list[dict[str, object]] = []
    result = await service._generate_segment_visual(segment or _segment(), notes)
    return result, notes


@pytest.mark.asyncio
async def test_a_refused_picture_does_not_sink_the_upload() -> None:
    result, _ = await _illustrate(Refuses())

    assert result is not None, "a refused picture still lost the whole upload"
    assert result.visual_variant is None


@pytest.mark.asyncio
async def test_the_teaching_text_survives_a_refused_picture() -> None:
    original = _segment()
    result, _ = await _illustrate(Refuses(), original)

    assert result.body == original.body
    assert result.title == original.title


@pytest.mark.asyncio
async def test_the_teacher_is_never_told_which_rule_fired() -> None:
    """Lydia, 9 November: a safety stop names no rule and no trigger.

    The note says a check held the picture back and which section. It must
    not carry the categories or the phase, in any field: the app would have
    nothing to render them as, and the ruling is that she is not told.
    """
    _, notes = await _illustrate(
        Refuses(categories=("privacy_abuse", "self_harm"), phase="image_output")
    )

    note = next(item for item in notes if item["code"] == "visual_blocked_by_safety")
    assert note["segment"] == "food-chains-2"
    assert "categories" not in note
    assert "phase" not in note
    written = " ".join(str(value) for value in note.values()).casefold()
    for leak in ("privacy_abuse", "self_harm", "image_output", "image_prompt"):
        assert leak not in written, f"{leak} reached the teacher's note"


@pytest.mark.asyncio
async def test_the_note_tells_a_teacher_what_to_do_about_a_wrong_refusal() -> None:
    _, notes = await _illustrate(Refuses())

    message = next(item for item in notes if item["code"] == "visual_blocked_by_safety")["message"]
    assert "Its teaching text is unchanged" in message
    # Routes a wrong refusal to us rather than leaving her to edit her file.
    assert "we will look at the check rather than your material" in message


@pytest.mark.asyncio
async def test_the_section_is_put_in_front_of_a_teacher() -> None:
    result, _ = await _illustrate(Refuses())

    assert result.needs_review is True
    assert "visual_blocked_by_safety" in result.review_reasons


@pytest.mark.asyncio
async def test_a_refusal_reads_differently_from_a_crash() -> None:
    """A teacher can tell "we would not draw this" from "the drawing failed"."""
    _, refused = await _illustrate(Refuses())
    _, broken = await _illustrate(Breaks())

    assert {item["code"] for item in refused} == {"visual_blocked_by_safety"}
    assert {item["code"] for item in broken} == {"visual_generation_failed"}


@pytest.mark.asyncio
async def test_a_crash_still_drops_the_picture_the_way_it_always_did() -> None:
    result, _ = await _illustrate(Breaks())

    assert result.visual_variant is None
    assert result.needs_review is True
    assert "visual_generation_failed" in result.review_reasons


@pytest.mark.asyncio
async def test_the_child_facing_wording_never_names_a_safety_category() -> None:
    generator = Refuses()
    with pytest.raises(VisualGenerationError) as caught:
        await generator.generate()

    assert "privacy_abuse" not in str(caught.value)
    assert isinstance(caught.value.__cause__, SafetyBlocked)


def test_the_lesson_source_is_still_checked_before_any_section_exists() -> None:
    """The gate that matters is untouched: a refused lesson still fails.

    Asserted on position, because the point is that the source check is not
    inside the per-picture handler this change made forgiving.
    """
    from nevo.content_parsing import service

    source = service.__loader__.get_source(service.__name__)
    assert 'phase="lesson_source"' in source[: source.index("blocked = error.__cause__")]


@pytest.mark.asyncio
async def test_we_can_still_tell_a_real_refusal_from_a_false_positive(caplog) -> None:
    """The detail has to survive somewhere, or Food Chains is unexplainable again.

    Withholding it from the teacher is the ruling; losing it entirely would
    put us back where seven uploads failed and nothing said "safety".
    """
    import logging

    with caplog.at_level(logging.WARNING):
        await _illustrate(Refuses(categories=("privacy_abuse",), phase="image_prompt"))

    logged = " ".join(item.getMessage() for item in caplog.records)
    assert "privacy_abuse" in logged
    assert "image_prompt" in logged
    assert "food-chains-2" in logged
