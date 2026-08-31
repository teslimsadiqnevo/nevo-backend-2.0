"""Segment duration estimate tests."""
from nevo.content_parsing.entities import ParsedLessonSegment
from nevo.content_parsing.service import (
    WORDS_READ_PER_MINUTE,
    estimate_segment_minutes,
)
from nevo.domain.intelligence.vocabulary import ContentModality, LessonContentType


def _segment(body: str, content_type=LessonContentType.EXPLANATORY_TEXT, checkpoints=()):
    return ParsedLessonSegment(
        segment_key="s1",
        content_type=content_type,
        sequence_order=1,
        title="T",
        body=body,
        available_modalities=(ContentModality.TEXT,),
        comprehension_checkpoints=checkpoints,
    )


def test_reading_time_scales_with_word_count() -> None:
    short = estimate_segment_minutes(_segment(" ".join(["word"] * WORDS_READ_PER_MINUTE)))
    long = estimate_segment_minutes(_segment(" ".join(["word"] * WORDS_READ_PER_MINUTE * 4)))

    assert short == 1
    assert long == 4


def test_a_short_segment_is_never_zero_minutes() -> None:
    assert estimate_segment_minutes(_segment("Short.")) == 1


def test_an_empty_segment_still_costs_a_minute() -> None:
    assert estimate_segment_minutes(_segment("")) == 1


def test_practice_questions_have_a_thinking_floor() -> None:
    """A two-line question costs more than its reading time."""
    question = _segment("What is 2 + 2?", content_type=LessonContentType.PRACTICE_QUESTION)
    prose = _segment("What is 2 + 2?")

    assert estimate_segment_minutes(question) == 3
    assert estimate_segment_minutes(prose) == 1


def test_calculations_and_worked_examples_have_their_own_floors() -> None:
    body = "Solve."
    calculation = _segment(body, content_type=LessonContentType.CALCULATION)
    worked = _segment(body, content_type=LessonContentType.WORKED_EXAMPLE)

    assert estimate_segment_minutes(calculation) == 3
    assert estimate_segment_minutes(worked) == 2


def test_each_checkpoint_adds_a_minute() -> None:
    body = " ".join(["word"] * WORDS_READ_PER_MINUTE)
    without = estimate_segment_minutes(_segment(body))
    with_two = estimate_segment_minutes(_segment(body, checkpoints=({"q": 1}, {"q": 2})))

    assert with_two == without + 2
