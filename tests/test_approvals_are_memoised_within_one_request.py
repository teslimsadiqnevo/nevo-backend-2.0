"""The approval lookups are cached per request, and the cache cannot go stale.

approved_check_ids and approved_level_ids load every segment of a lesson and
re-render every question in it. Answering one check called them three times
for the same lesson, and a nine-section lesson paid for all of it while the
child waited to see a tick.

The cache is keyed per request and dropped the moment anything it reads is
about to be written. These tests pin that property - same answer before and
after a write - rather than the mechanism, so a later change of mechanism
still has to keep the answer right.
"""

from __future__ import annotations

import pytest

from nevo.api import lesson_review
from nevo.db.models.content import Lesson, LessonSegment


class Unrelated:
    """A pending write that has nothing to do with approvals."""


class FakeSession:
    """Enough of a Session to exercise the memo and the flush hook."""

    def __init__(self) -> None:
        self.info: dict = {}
        self.new: set = set()
        self.dirty: set = set()
        self.deleted: set = set()


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


async def test_the_second_call_in_one_request_does_not_repeat_the_work(session, monkeypatch):
    calls = []

    async def counted(_session, lesson_id):
        calls.append(lesson_id)
        return {("segment-1", "question-1")}

    monkeypatch.setattr(lesson_review, "_approved_check_ids", counted)

    first = await lesson_review.approved_check_ids(session, "lesson-1")
    second = await lesson_review.approved_check_ids(session, "lesson-1")

    assert first == second == {("segment-1", "question-1")}
    assert len(calls) == 1, "the lesson was re-read for an answer already in hand"


async def test_a_different_lesson_is_not_served_another_lesson_s_answer(session, monkeypatch):
    async def per_lesson(_session, lesson_id):
        return {(f"segment-of-{lesson_id}", "question-1")}

    monkeypatch.setattr(lesson_review, "_approved_check_ids", per_lesson)

    one = await lesson_review.approved_check_ids(session, "lesson-1")
    two = await lesson_review.approved_check_ids(session, "lesson-2")

    assert one != two
    assert one == {("segment-of-lesson-1", "question-1")}
    assert two == {("segment-of-lesson-2", "question-1")}


async def test_checks_and_levels_do_not_share_a_cache_entry(session, monkeypatch):
    async def checks(_session, _lesson_id):
        return {("owner", "from-checks")}

    async def levels(_session, _lesson_id):
        return {("owner", "from-levels")}

    monkeypatch.setattr(lesson_review, "_approved_check_ids", checks)
    monkeypatch.setattr(lesson_review, "_approved_level_ids", levels)

    assert await lesson_review.approved_check_ids(session, "lesson-1") == {("owner", "from-checks")}
    assert await lesson_review.approved_level_ids(session, "lesson-1") == {("owner", "from-levels")}


@pytest.mark.parametrize("bucket", ["new", "dirty", "deleted"])
@pytest.mark.parametrize(
    "written",
    [
        pytest.param(Lesson, id="lesson"),
        pytest.param(LessonSegment, id="segment"),
    ],
)
async def test_a_write_to_anything_the_answer_reads_drops_the_cache(
    session, monkeypatch, bucket, written
):
    answers = [{("segment-1", "before")}, {("segment-1", "after")}]

    async def changing(_session, _lesson_id):
        return answers.pop(0)

    monkeypatch.setattr(lesson_review, "_approved_check_ids", changing)

    assert await lesson_review.approved_check_ids(session, "lesson-1") == {("segment-1", "before")}

    getattr(session, bucket).add(written.__new__(written))
    lesson_review._forget_approvals_on_write(session, None, None)

    again = await lesson_review.approved_check_ids(session, "lesson-1")
    assert again == {("segment-1", "after")}, (
        "a cached approval survived a write to the content it is derived from"
    )


async def test_a_write_to_something_unrelated_keeps_the_cache(session, monkeypatch):
    calls = []

    async def counted(_session, lesson_id):
        calls.append(lesson_id)
        return {("segment-1", "question-1")}

    monkeypatch.setattr(lesson_review, "_approved_check_ids", counted)

    await lesson_review.approved_check_ids(session, "lesson-1")
    session.dirty.add(Unrelated())
    lesson_review._forget_approvals_on_write(session, None, None)
    await lesson_review.approved_check_ids(session, "lesson-1")

    assert len(calls) == 1


async def test_forgetting_one_lesson_leaves_the_others_alone(session, monkeypatch):
    calls = []

    async def counted(_session, lesson_id):
        calls.append(lesson_id)
        return {(f"segment-of-{lesson_id}", "question-1")}

    monkeypatch.setattr(lesson_review, "_approved_check_ids", counted)

    await lesson_review.approved_check_ids(session, "lesson-1")
    await lesson_review.approved_check_ids(session, "lesson-2")
    lesson_review.forget_approvals(session, "lesson-1")
    await lesson_review.approved_check_ids(session, "lesson-1")
    await lesson_review.approved_check_ids(session, "lesson-2")

    assert calls == ["lesson-1", "lesson-2", "lesson-1"]


async def test_forgetting_before_anything_was_cached_is_harmless(session):
    lesson_review.forget_approvals(session)
    lesson_review.forget_approvals(session, "lesson-1")
    lesson_review._forget_approvals_on_write(session, None, None)
