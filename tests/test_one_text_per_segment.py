"""The teacher and the child read the same words.

segment.body and textVariant.body were two independently settable strings. The
student player builds the text modality from the first; the teacher's review
screen reads the second. If the model ever returned a text_variant body of its
own it would have won, and a teacher would have approved text no child saw -
the approval gate guarding the wrong string.

Every segment in the library has them identical, because nothing asked the
model for a separate one. That was luck, not a guarantee.
"""

from __future__ import annotations

import pytest

from nevo.api.lesson_contracts import TextVariant
from nevo.content_parsing.service import _text_variant


def test_the_model_cannot_supply_a_second_body() -> None:
    variant = _text_variant({"body": "Words the child would never see"}, "The segment's text.")

    assert variant["body"] == "The segment's text."


def test_a_missing_variant_still_yields_the_segment_text() -> None:
    assert _text_variant(None, "The segment's text.")["body"] == "The segment's text."


@pytest.mark.parametrize(
    "supplied",
    [None, {}, {"body": ""}, {"body": "other"}, {"keyPoints": ["a"]}, "not a dict"],
    ids=["none", "empty", "blank body", "other body", "points only", "wrong type"],
)
def test_whatever_the_model_sends_the_two_agree(supplied: object) -> None:
    body = "Interest is what a bank pays you for leaving money there."

    assert _text_variant(supplied, body)["body"] == body


class TestKeyPoints:
    def test_they_sit_beside_the_body_rather_than_retelling_it(self) -> None:
        body = "Simple interest is worked out on the original principal only."
        variant = _text_variant({"keyPoints": [body, "Principal never changes"]}, body)

        # The one that restates the whole body is dropped rather than shown twice.
        assert variant["keyPoints"] == ["Principal never changes"]

    def test_case_and_padding_do_not_smuggle_a_retelling_through(self) -> None:
        body = "Interest is paid every year."
        variant = _text_variant({"keyPoints": ["  INTEREST IS PAID EVERY YEAR.  "]}, body)

        assert variant["keyPoints"] == []

    def test_there_is_a_ceiling(self) -> None:
        variant = _text_variant({"keyPoints": [f"point {n}" for n in range(20)]}, "body")

        assert len(variant["keyPoints"]) <= 6
        assert TextVariant.model_validate(variant)

    def test_the_contract_agrees_with_the_parse(self) -> None:
        # A parse that produced more than the contract accepts would 500 on read.
        assert TextVariant.model_fields["key_points"].metadata[0].max_length == 6
