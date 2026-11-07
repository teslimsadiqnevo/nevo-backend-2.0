"""Who wrote a check, and which checks a child may be asked.

Two reports from the console on 6 November, both about the same missing
distinction.

The checks review could not tell a check whose answer came out of the
teacher's file - with a mastery level Nevo picked - from one Nevo wrote
outright. Both arrived needing a decision and looked identical.

Delivery held back every check without a sign-off, which was read for a day
as too wide and narrowed to generated questions only. Lydia's ruling of
7 November settles it the other way: nothing reaches a child until the
whole lesson is reviewed, whoever wrote the question and whoever wrote the
answer. Holding the questions back was right; what was missing was the
lesson refusing to be assigned while any were outstanding, which is pinned
in test_a_lesson_is_not_assignable_with_unreviewed_questions.
"""

from __future__ import annotations

from nevo.api.lesson_contracts import student_checkpoint_payloads
from nevo.main import app

SPEC = app.openapi()


def _question(**overrides: object) -> dict[str, object]:
    question = {
        "id": "q1",
        "prompt": "What is one half of four?",
        "answerType": "numeric",
        "answerKey": 2,
    }
    question.update(overrides)
    return question


def test_the_review_says_who_wrote_the_answer() -> None:
    properties = SPEC["components"]["schemas"]["CheckReviewItem"]["properties"]
    assert "authoredBy" in properties
    # Both, because they answer different questions: whose the answer is, and
    # whose the level is. A check can be the teacher's with a level Nevo
    # picked, which is the case the screen could not see.
    assert "masteryLevelAuthoredBy" in properties


def test_no_question_is_delivered_before_sign_off() -> None:
    # Whoever wrote it. The narrow version delivered a question whose answer
    # came from the teacher's file without one, and the ruling of 7 November
    # is that the lesson is not assignable at all in that state.
    for author in ("person", "nevo"):
        assert (
            student_checkpoint_payloads(
                [_question(authoredBy=author)],
                segment_key="s1",
                reviewed_question_ids=set(),
            )
            == []
        ), author


def test_a_signed_off_question_is_delivered() -> None:
    for author in ("person", "nevo"):
        delivered = student_checkpoint_payloads(
            [_question(authoredBy=author)],
            segment_key="s1",
            reviewed_question_ids={"q1"},
        )
        assert [item["id"] for item in delivered] == ["q1"], author


def test_an_unmarkable_question_is_never_delivered() -> None:
    # No answer means nothing to mark against, sign-off or not.
    assert (
        student_checkpoint_payloads(
            [_question(authoredBy="person", answerKey=None)],
            segment_key="s1",
            reviewed_question_ids={"q1"},
        )
        == []
    )


def test_a_level_nevo_picked_is_withheld_from_a_signed_off_question() -> None:
    # The question is asked, because a teacher signed it off. The level is
    # not shown, because Nevo chose it and that choice has its own sign-off.
    delivered = student_checkpoint_payloads(
        [
            _question(
                authoredBy="person",
                masteryLevel="application",
                masteryLevelAuthoredBy="nevo",
            )
        ],
        segment_key="s1",
        reviewed_question_ids={"q1"},
        reviewed_level_ids=set(),
    )
    assert [item["id"] for item in delivered] == ["q1"]
    assert delivered[0]["masteryLevel"] is None
