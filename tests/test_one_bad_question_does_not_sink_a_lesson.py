"""One question nobody can mark must not cost a teacher their whole lesson.

8 November. Density.pdf failed at finding_sections with "Unclassifiable
question after three targeted corrections", and the retry saved a text-only
fallback with no checks, no key points, no guided steps and no levels -
nothing to test levels or transfer on. The file contained an open question a
teacher had written for discussion: "Why does an egg float in very salty
water?". There is no answer to mark against, so no renderer can take it.

Every other parse failure degrades to a text fallback with a note. This one
alone re-raised and took the upload down.

It raised because an unrenderable question must not reach a child. Since
SCRUM-307 it cannot: a question without a current sign-off is withheld from
delivery, and a lesson with any unreviewed check is not assignable at all.
So failing the parse buys no safety any more and costs the lesson.
"""

from __future__ import annotations

import inspect

from nevo.api.lesson_contracts import UnclassifiableQuestionError, checkpoint_payloads
from nevo.content_parsing import service
from nevo.content_parsing.service import _drop_unusable_questions

OPEN = {"id": "q1", "prompt": "Why does an egg float in very salty water?"}
MARKABLE = {
    "id": "q2",
    "prompt": "Which one floats?",
    "answerType": "single_choice",
    "answerKey": "a",
    "options": [{"value": "a", "label": "Egg"}, {"value": "b", "label": "Rock"}],
}


def test_the_open_question_really_is_unrenderable() -> None:
    # The premise. Without an answer there is nothing to mark against.
    try:
        checkpoint_payloads([OPEN], segment_key="s1", strict=True)
    except UnclassifiableQuestionError:
        return
    raise AssertionError("expected the open question to be refused")


def test_only_the_unusable_question_is_dropped() -> None:
    payload = {"segments": [{"comprehension_checkpoints": [dict(OPEN), dict(MARKABLE)]}]}
    dropped = _drop_unusable_questions(payload)

    assert dropped == ["Why does an egg float in very salty water?"]
    kept = payload["segments"][0]["comprehension_checkpoints"]
    assert [item["id"] for item in kept] == ["q2"]


def test_both_key_spellings_are_filtered() -> None:
    # The model returns one or the other, and filtering only one would leave
    # the unusable question in place and the parse still failing.
    payload = {"segments": [{"comprehensionCheckpoints": [dict(OPEN), dict(MARKABLE)]}]}
    _drop_unusable_questions(payload)
    assert [q["id"] for q in payload["segments"][0]["comprehensionCheckpoints"]] == ["q2"]


def test_the_assessment_is_filtered_too() -> None:
    payload = {"assessment": [dict(OPEN), dict(MARKABLE)]}
    _drop_unusable_questions(payload)
    assert [item["id"] for item in payload["assessment"]] == ["q2"]


def test_what_was_dropped_is_named() -> None:
    # A shorter lesson with no explanation is the failure the parse notes
    # exist to prevent. The teacher is told which question went.
    payload = {"assessment": [dict(OPEN)]}
    assert _drop_unusable_questions(payload) == [
        "Why does an egg float in very salty water?"
    ]


def test_a_dropped_question_is_reported_as_a_review_note() -> None:
    from nevo.content_parsing import service

    source = inspect.getsource(service)
    assert '"code": "question_unusable"' in source
    assert '"questions": dropped' in source


def test_the_parse_no_longer_dies_on_one_of_them() -> None:
    from nevo.content_parsing import service

    source = inspect.getsource(service)
    # Dropped after repair has had its three goes, not instead of repair.
    assert "_drop_unusable_questions(candidate)" in source


def test_repair_giving_up_is_caught_as_well_as_repair_failing() -> None:
    """Two ways repair ends badly, and 859fb02 only handled one.

    repair_questions either returns a payload that still will not render, or
    raises "Unclassifiable question after three targeted corrections" and
    gives up. The first was handled. The second was not, because the call
    sits inside the except block it would have been caught by, so the raise
    went straight past.

    Pressure.pdf lost three uploads to it on 8 November, after the fix that
    was supposed to stop exactly that.
    """

    source = inspect.getsource(service.ContentParsingService.parse)
    repair = source[source.index("repair_questions("):]
    # The call itself is guarded, not only what comes after it.
    assert "except UnclassifiableQuestionError:" in repair[: repair.index("_mark_source_authorship")]


def test_the_unrepaired_payload_is_what_gets_dropped_from() -> None:
    # When repair raises, the assignment never happens, so candidate still
    # holds the pre-repair payload - which is the one with the questions to
    # drop in it.
    source = inspect.getsource(service.ContentParsingService.parse)
    assert "_drop_unusable_questions(candidate)" in source
