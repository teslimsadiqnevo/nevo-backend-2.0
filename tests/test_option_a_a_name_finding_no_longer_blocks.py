"""Lydia's Option A, 12 November.

A privacy_abuse finding on Nevo's own lesson text no longer blocks. Every other
category still blocks, the uploaded file still gets its own privacy check
first, and such a finding is still recorded with the text so a true positive
would show.

And her safeguarding ruling: a name block does not go on the safeguarding list
at all. Only categories an adult needs to act on stay.
"""

from __future__ import annotations

import pytest

from nevo.ai_gateway import safety as safety_module
from nevo.api.safety_retention import NOT_ACTIONABLE_ALONE


class Decision:
    def __init__(self, action: str, categories) -> None:
        self.action = action
        self.categories = list(categories)


@pytest.fixture
def guard():
    cls = next(
        value
        for value in vars(safety_module).values()
        if hasattr(value, "_privacy_finding_on_our_own_text")
    )
    return cls, object.__new__(cls)


def _allowed(guard, phase: str, action="block", categories=("privacy_abuse",)) -> bool:
    cls, instance = guard
    return cls._privacy_finding_on_our_own_text(instance, Decision(action, categories), phase)


# --- what no longer blocks --------------------------------------------------


@pytest.mark.parametrize(
    "phase",
    [
        "output:content_parse.default",
        "input:content_parse.default",
        "final:content_parse.default",
        "output:lesson_depth.default",
        "final:lesson_depth.default",
        "output:content_question_repair.default",
        "lesson_narration",
        "illustration_source",
    ],
)
def test_a_name_finding_on_our_own_text_is_allowed_through(guard, phase: str) -> None:
    assert _allowed(guard, phase)


# --- what still blocks ------------------------------------------------------


def test_the_uploaded_file_still_gets_its_own_privacy_check(guard) -> None:
    """Lydia's condition. lesson_source is the file's first look and must refuse."""
    assert not _allowed(guard, "lesson_source")


@pytest.mark.parametrize("phase", ["lesson_rewrite", "rewrite_approval"])
def test_words_a_person_just_typed_still_block(guard, phase: str) -> None:
    """A rewrite has never been privacy-checked, so a real name is possible."""
    assert not _allowed(guard, phase)


@pytest.mark.parametrize("phase", ["input:ask_nevo.teacher", "output:ask_nevo.teacher"])
def test_ask_nevo_still_blocks(guard, phase: str) -> None:
    """A question about a named child is the point there, and Lydia kept it."""
    assert not _allowed(guard, phase)


@pytest.mark.parametrize("phase", ["image_prompt", "image_output", "image_cached"])
def test_the_image_phases_still_block(guard, phase: str) -> None:
    assert not _allowed(guard, phase)


@pytest.mark.parametrize(
    "categories",
    [("self_harm",), ("violence",), ("sexual_content",), ("privacy_abuse", "violence"), ()],
)
def test_every_other_category_still_blocks_on_our_own_text(guard, categories) -> None:
    """Including alongside privacy: the test is that privacy is all there is."""
    assert not _allowed(guard, "output:content_parse.default", categories=categories)


def test_an_allow_is_not_treated_as_an_allowed_finding(guard) -> None:
    assert not _allowed(guard, "output:content_parse.default", action="allow", categories=())


# --- the recording condition ------------------------------------------------


def test_the_text_is_kept_only_for_a_finding_we_let_through() -> None:
    """Her first condition, and why it is not every decision.

    There are 1,648 decisions against 47 parse runs, so recording the material
    every time would keep every lesson in the product several times over. The
    ones worth reading are the ones nobody acted on.
    """
    source = safety_module.__loader__.get_source(safety_module.__name__)
    assert "allowed_material=chunk if allowed_through else None" in source

    from nevo.db.models.safety import ContentSafetyEvent

    assert "allowed_material" in ContentSafetyEvent.__table__.c
    assert ContentSafetyEvent.__table__.c.allowed_material.nullable


def test_it_is_the_chunk_that_was_judged_not_the_whole_text() -> None:
    """check() splits at 16,000 characters and judges each piece separately.

    Keeping the whole text would not say which part was found, and the piece
    that was judged is the piece a person needs to read. It is also what
    explained the "allowed then blocked a second apart" pair: one output, two
    chunks, the first allowed and the second blocked.
    """
    source = safety_module.__loader__.get_source(safety_module.__name__)
    judged = source[source.index("for chunk in chunks:") :]
    assert "allowed_material=chunk" in judged[: judged.index("def _headers")]


# --- the safeguarding list --------------------------------------------------


def test_a_bare_name_finding_is_not_on_the_safeguarding_list() -> None:
    from nevo.api import safety_retention

    source = safety_retention.__loader__.get_source(safety_retention.__name__)
    assert NOT_ACTIONABLE_ALONE == "privacy_abuse"
    assert "actionable_by_an_adult()" in source
    # Applied to the list and to acknowledging, so the two cannot disagree.
    assert source.count("actionable_by_an_adult()") >= 2


def test_a_name_finding_alongside_something_else_still_appears() -> None:
    """The anything-else is the part that matters."""
    from nevo.api.safety_retention import actionable_by_an_adult

    rendered = str(actionable_by_an_adult())
    # Exactly one category, and that one being a name, is the only exclusion.
    assert "jsonb_array_length" in rendered
    assert "NOT" in rendered.upper()


def test_a_childs_profile_uses_the_same_rule() -> None:
    from nevo.api import product_learning

    source = product_learning.__loader__.get_source(product_learning.__name__)
    assert "actionable_by_an_adult()" in source
