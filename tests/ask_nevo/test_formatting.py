"""Structuring whatever the model happens to return."""
from nevo.ask_nevo.formatting import (
    AnswerBlockType,
    AnswerFormat,
    strip_inline_markup,
    structure_answer,
)


def test_plain_prose_becomes_one_paragraph() -> None:
    result = structure_answer("Amara is doing well and finished every task.")

    assert result.format is AnswerFormat.PLAIN
    assert len(result.blocks) == 1
    assert result.blocks[0].type is AnswerBlockType.PARAGRAPH
    assert result.blocks[0].text == "Amara is doing well and finished every task."


def test_wrapped_prose_joins_into_one_paragraph() -> None:
    result = structure_answer("Amara is doing well\nand finished every task.")

    assert len(result.blocks) == 1
    assert result.blocks[0].text == "Amara is doing well and finished every task."


def test_a_blank_line_starts_a_new_paragraph() -> None:
    result = structure_answer("First point.\n\nSecond point.")

    assert [block.text for block in result.blocks] == ["First point.", "Second point."]


def test_markdown_bullets_become_a_bullet_block() -> None:
    result = structure_answer("Try these:\n- Recap fractions\n- Use a number line")

    assert result.format is AnswerFormat.STRUCTURED
    bullets = [b for b in result.blocks if b.type is AnswerBlockType.BULLETS]
    assert bullets[0].items == ("Recap fractions", "Use a number line")


def test_asterisk_and_unicode_bullets_are_both_recognised() -> None:
    for marker in ("*", "•", "·"):
        result = structure_answer(f"{marker} One\n{marker} Two")
        bullets = [b for b in result.blocks if b.type is AnswerBlockType.BULLETS]
        assert bullets[0].items == ("One", "Two"), marker


def test_numbered_lines_become_steps_not_bullets() -> None:
    result = structure_answer("1. Recap the example\n2. Ask one check question")

    steps = [b for b in result.blocks if b.type is AnswerBlockType.STEPS]
    assert steps[0].items == ("Recap the example", "Ask one check question")


def test_markdown_headings_are_captured_with_their_level() -> None:
    result = structure_answer("## Where she is\nShe is secure on halves.")

    heading = result.blocks[0]
    assert heading.type is AnswerBlockType.HEADING
    assert heading.text == "Where she is"
    assert heading.level == 2


def test_a_short_line_ending_in_a_colon_reads_as_a_heading() -> None:
    """Models introduce lists this way constantly without using markdown."""
    result = structure_answer("Next steps:\n- Recap fractions")

    assert result.blocks[0].type is AnswerBlockType.HEADING
    assert result.blocks[0].text == "Next steps"


def test_emphasis_markers_never_reach_the_client() -> None:
    """A teacher must never see a literal ** in the answer."""
    result = structure_answer("Amara is **secure** on _halves_ and `quarters`.")

    assert "*" not in result.blocks[0].text
    assert "_" not in result.blocks[0].text
    assert "`" not in result.blocks[0].text
    assert result.blocks[0].text == "Amara is secure on halves and quarters."


def test_mixed_prose_lists_and_headings_all_survive() -> None:
    result = structure_answer(
        "Amara is secure on halves.\n\n"
        "## Next steps\n"
        "1. Recap the worked example\n"
        "2. Ask one check question\n\n"
        "Watch for:\n"
        "- Rushing the last question"
    )

    kinds = [block.type for block in result.blocks]
    assert AnswerBlockType.PARAGRAPH in kinds
    assert AnswerBlockType.HEADING in kinds
    assert AnswerBlockType.STEPS in kinds
    assert AnswerBlockType.BULLETS in kinds


def test_plain_text_flattens_every_block_for_simple_clients() -> None:
    result = structure_answer("Next steps:\n1. Recap\n2. Check\n\nWatch pace.")

    assert result.plain_text == "Next steps\n1. Recap\n2. Check\nWatch pace."


def test_an_empty_answer_produces_no_blocks() -> None:
    for value in ("", "   ", "\n\n"):
        result = structure_answer(value)
        assert result.blocks == ()
        assert result.plain_text == ""


def test_a_list_that_starts_immediately_still_parses() -> None:
    result = structure_answer("- One\n- Two")

    assert result.blocks[0].type is AnswerBlockType.BULLETS
    assert result.blocks[0].items == ("One", "Two")


def test_consecutive_lists_of_different_kinds_do_not_merge() -> None:
    result = structure_answer("- Bullet one\n1. Step one")

    assert [b.type for b in result.blocks] == [
        AnswerBlockType.BULLETS,
        AnswerBlockType.STEPS,
    ]


def test_strip_inline_markup_tidies_spacing_left_behind() -> None:
    assert strip_inline_markup("Amara is  **secure** .") == "Amara is secure."


def test_the_fallback_answer_structures_cleanly() -> None:
    """The rule-based fallback is plain prose and must not confuse the parser."""
    result = structure_answer(
        "I can help with this, but I need the live assistant connection to give "
        "a specific answer."
    )

    assert result.format is AnswerFormat.PLAIN
    assert len(result.blocks) == 1
