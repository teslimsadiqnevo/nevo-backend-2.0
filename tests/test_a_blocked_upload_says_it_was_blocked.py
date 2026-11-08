"""A safety block must say so, and must not fire on a lesson character.

Food Chains.pdf failed seven times on 8 November at receiving_file. The
recorded decision was block / privacy_abuse on lesson_source, and the text
is ordinary biology - its only named people are "Ngozi says X, Efe says Y,
who is right?" in a multiple-choice question.

Two faults. SafetyBlocked was raised bare, so str() was empty, the stored
error_message was empty and the teacher read "nothing you did caused it".
And the rule that lesson characters are not personal data was already in
the prompt, buried in a paragraph, and was not being followed.
"""

from __future__ import annotations

from nevo.ai_gateway import safety
from nevo.ai_gateway.safety import SafetyBlocked, SafetyUnavailable
from nevo.content_parsing.failures import GENERIC_FAILURE, failure_reason


def test_a_block_carries_what_was_blocked() -> None:
    error = SafetyBlocked(("privacy_abuse",), "lesson_source")
    assert error.categories == ("privacy_abuse",)
    assert error.phase == "lesson_source"
    assert "privacy_abuse" in str(error)
    assert "lesson_source" in str(error)


def test_even_a_bare_block_leaves_a_message() -> None:
    # Nothing may raise this with an empty str() again.
    assert str(SafetyBlocked()).strip()


def test_a_blocked_upload_is_not_reported_as_a_mystery() -> None:
    for error in (SafetyBlocked(("privacy_abuse",), "lesson_source"), SafetyBlocked()):
        reason = failure_reason(error)
        assert reason != GENERIC_FAILURE
        assert "safety check" in reason


def test_an_unavailable_check_is_told_apart_from_a_block() -> None:
    # One means try again, the other means the file was refused. Reporting
    # both as the generic sentence sent teachers to re-upload a file that
    # would be refused every time.
    blocked = failure_reason(SafetyBlocked())
    unavailable = failure_reason(SafetyUnavailable())
    assert blocked != unavailable
    assert "try again" in unavailable


def test_the_prompt_allows_named_lesson_characters() -> None:
    # Normalised, because the prompt is hard-wrapped and a rule should not
    # be assertable only where the line breaks happen to fall.
    prompt = " ".join(safety.SAFETY_INSTRUCTION.split())
    assert "characters, not personal data" in prompt
    # Stated as its own rule rather than a clause inside the privacy
    # paragraph, which is where it was being missed.
    assert "Never return privacy_abuse for first names" in prompt
    assert "ordinary biology and must be allowed" in prompt
