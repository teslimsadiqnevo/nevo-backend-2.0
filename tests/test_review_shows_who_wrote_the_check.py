"""Who wrote a check, and which checks a child may be asked.

Two reports from the console on 6 November, both about the same missing
distinction.

The checks review could not tell a check whose answer came out of the
teacher's file - with a mastery level Nevo picked - from one Nevo wrote
outright. Both arrived needing a decision and looked identical.

And student delivery held back every check without a sign-off, not only the
generated ones. Lydia's condition of 2 November is about questions Nevo
wrote; a question whose answer was in the teacher's own file is already a
person's work. So a lesson's own questions vanished from delivery until
somebody signed off checks nobody had said needed signing.
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


def test_a_question_from_the_teachers_file_is_delivered_unsigned() -> None:
    delivered = student_checkpoint_payloads(
        [_question(authoredBy="person")],
        segment_key="s1",
        reviewed_question_ids=set(),
    )
    assert [item["id"] for item in delivered] == ["q1"]


def test_a_question_nevo_wrote_still_waits_for_sign_off() -> None:
    held = student_checkpoint_payloads(
        [_question(authoredBy="nevo")],
        segment_key="s1",
        reviewed_question_ids=set(),
    )
    assert held == []

    signed = student_checkpoint_payloads(
        [_question(authoredBy="nevo")],
        segment_key="s1",
        reviewed_question_ids={"q1"},
    )
    assert [item["id"] for item in signed] == ["q1"]


def test_an_unmarkable_question_is_never_delivered() -> None:
    # No answer means nothing to mark against, whoever wrote it.
    assert (
        student_checkpoint_payloads(
            [_question(authoredBy="person", answerKey=None)],
            segment_key="s1",
            reviewed_question_ids={"q1"},
        )
        == []
    )


def test_a_level_nevo_picked_is_still_withheld_from_a_teachers_question() -> None:
    # The narrower rule the ruling asks for: the question is asked, because a
    # person wrote it, and the level is not shown, because Nevo chose it.
    delivered = student_checkpoint_payloads(
        [
            _question(
                authoredBy="person",
                masteryLevel="application",
                masteryLevelAuthoredBy="nevo",
            )
        ],
        segment_key="s1",
        reviewed_question_ids=set(),
        reviewed_level_ids=set(),
    )
    assert [item["id"] for item in delivered] == ["q1"]
    assert delivered[0]["masteryLevel"] is None
