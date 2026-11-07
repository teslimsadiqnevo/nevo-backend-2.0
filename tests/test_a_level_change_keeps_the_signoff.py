"""Correcting a check's level does not revoke the checks approval.

SCRUM-308, Lydia's ruling of 7 November: a level change is an edit, and
nothing about it is a new approval, so the sign-off stays in place.

The mastery level was part of each check's material, and the checks sign-off
is a hash of that material. So a teacher correcting a wrongly tagged level
invalidated the approval, which pulled the questions back from children on a
lesson that was already live - and after SCRUM-307 made every review step
gate assignment, it also made that live lesson unassignable. A wrong tag
holds a child at the wrong place, so correcting one has to be cheap.

The level is not unreviewed as a result. It has its own sign-off, which is
where that decision belongs.
"""

from __future__ import annotations

import inspect

from nevo.api import lesson_review
from nevo.api.lesson_review import _hash, checks_signoff_material


def _check(level: str | None) -> dict[str, object]:
    item: dict[str, object] = {
        "segmentId": "s1",
        "questionId": "q1",
        "questionPrompt": "What is one half of four?",
        "questionAnswerType": "numeric",
        "questionAnswerKey": 2,
    }
    if level is not None:
        item["masteryLevel"] = level
        item["masteryLevelAuthoredBy"] = "nevo"
    return item


def test_changing_the_level_does_not_change_the_signed_hash() -> None:
    knowledge = _hash(checks_signoff_material([_check("knowledge")]))
    application = _hash(checks_signoff_material([_check("application")]))
    untagged = _hash(checks_signoff_material([_check(None)]))
    assert knowledge == application == untagged


def test_changing_the_question_still_does_change_it() -> None:
    # The sign-off still means something: editing the prompt or the answer
    # is a change to what was approved, and has to be approved again.
    original = _hash(checks_signoff_material([_check("knowledge")]))
    edited = dict(_check("knowledge"))
    edited["questionAnswerKey"] = 3
    assert _hash(checks_signoff_material([edited])) != original

    reworded = dict(_check("knowledge"))
    reworded["questionPrompt"] = "What is half of four?"
    assert _hash(checks_signoff_material([reworded])) != original


def test_the_level_is_the_only_thing_dropped() -> None:
    kept = checks_signoff_material([_check("knowledge")])[0]
    assert set(kept) == {
        "segmentId",
        "questionId",
        "questionPrompt",
        "questionAnswerType",
        "questionAnswerKey",
    }


def test_every_place_that_hashes_the_checks_signoff_uses_it() -> None:
    # Approving writes the hash and three places compare against it. If any
    # one of them hashed the raw material instead, the approval would read
    # as stale the moment a level changed - which is the bug.
    source = inspect.getsource(lesson_review)
    assert source.count("checks_signoff_material(") >= 4
    assert '"checks": _hash(checks_material)' not in source


def test_the_stored_snapshot_is_the_projection_too() -> None:
    # _current_signoff falls back to comparing the snapshot for key points,
    # and a snapshot carrying levels would disagree with the hash.
    source = inspect.getsource(lesson_review.approve_all_checks)
    assert "content_snapshot=signoff_material" in source
    assert "digest = _hash(signoff_material)" in source
