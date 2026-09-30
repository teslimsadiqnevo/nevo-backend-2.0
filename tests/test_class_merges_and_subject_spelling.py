"""One class written four ways, and one subject written two. SCRUM-204.

A four-hundred-row hand-maintained spreadsheet carries JSS 2A, JSS2A, Jss 2a
and JSS 2 A for one cohort. Left alone that is four classes: the school is
invoiced for four headcounts and each of the four teachers sees a quarter of
their students. So the merge is proposed, a person settles it, and confirming
is refused server-side until they have - because the headcount per class is
what the invoice is built from.

The subject spelling question is the same problem with a different answer.
Maths and Mathematics split a child's mastery across two knowledge graphs and
halve their progress, so they are folded into one at import; but a spelling
does not change the invoice, so the question waits for the classes screen
instead of blocking payment.
"""

from __future__ import annotations

import inspect

import pytest

from nevo.api.onboarding import (
    _derived_classes,
    _merge_proposals,
    _read_rows,
    confirm_and_price,
)
from nevo.domain.accounts.classes import class_merge_key, normalise_class_name
from nevo.domain.onboarding.vocabulary import OnboardingRowKind
from nevo.domain.subjects.spelling import fuller, possible_pair
from nevo.main import app

FOUR_SPELLINGS = (
    b"first_name,last_name,class,date_of_birth,admission_number,guardian_email\n"
    b"Amara,Okafor,JSS 2A,2015-04-23,ADM001,ngozi@example.com\n"
    b"Tunde,Bello,JSS2A,2015-06-02,ADM002,bisi@example.com\n"
    b"Chidi,Eze,Jss 2a,2014-11-30,ADM003,uche@example.com\n"
    b"Sade,Adeyemi,JSS 2 A,2015-01-09,ADM004,kemi@example.com\n"
    b"Nneka,Obi,JSS 3B,2014-02-09,ADM005,obi@example.com\n"
)

TEACHERS = (
    b"first_name,last_name,email,subject,class\n"
    b"Bisi,Bello,bisi.bello@example.com,Mathematics,JSS 2A\n"
    b"Bisi,Bello,bisi.bello@example.com,Basic Science,JSS 2A\n"
    b"Femi,Adeoye,femi@example.com,English Language,JSS 3B\n"
)


def _proposals(raw: bytes = FOUR_SPELLINGS, decided: dict[str, str] | None = None):
    rows = _read_rows(raw, OnboardingRowKind.STUDENT)
    return rows, _merge_proposals(_derived_classes(rows), decided or {})


def test_four_spellings_of_one_class_are_proposed_as_one_merge() -> None:
    _rows, proposals = _proposals()

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.key == "jss2a"
    # Three candidates, not four: "JSS 2A" and "Jss 2a" differ only in case
    # and are already one class before anybody is asked - that much the
    # database enforces. What is left needs a person, because collapsing
    # spaces entirely is a guess about somebody's spacing.
    assert len(proposal.candidates) == 3
    # The headcount of the merged class is what would be invoiced, so it is
    # stated rather than left for the console to add up.
    assert proposal.student_count == 4
    # A class that arrived under one spelling is nobody's question.
    assert "jss3b" not in {item.key for item in proposals}


def test_the_reason_names_the_spellings_it_found() -> None:
    _rows, proposals = _proposals()

    reason = proposals[0].reason

    # An admin confirming a merge is agreeing to a headcount; they should be
    # able to see which names they are agreeing about.
    for spelling in ("JSS 2A", "JSS2A", "JSS 2 A"):
        assert spelling in reason


def test_a_settled_merge_is_not_asked_again() -> None:
    # Either answer settles it. "No, we really do run these separately" is a
    # legitimate answer, and a school that gave it can then confirm.
    for answer in ("merged", "separate"):
        _rows, proposals = _proposals(decided={"jss2a": answer})
        assert proposals == []


def test_merging_moves_every_spelling_onto_the_kept_name() -> None:
    rows, proposals = _proposals()
    keep = proposals[0].proposed_name

    for row in rows:
        if class_merge_key(row.normalised_class_name or "") == "jss2a":
            row.normalised_class_name = normalise_class_name(keep)

    derived = _derived_classes(rows)
    merged = [item for item in derived if item.normalised_name == normalise_class_name(keep)]
    assert len(merged) == 1
    # All four children, in one class, counted once.
    assert merged[0].student_count == 4


def test_confirming_is_refused_while_a_merge_is_unresolved() -> None:
    # Enforced in the route and not only in canConfirm, because a hidden
    # button is not a gate and this one decides an invoice.
    source = inspect.getsource(confirm_and_price)

    assert "class_merges_unresolved" in source
    assert "_merge_proposals" in source


def test_the_state_reports_the_proposals_and_withholds_confirmation() -> None:
    schema = app.openapi()["components"]["schemas"]["OnboardingState"]

    assert "classMerges" in schema["properties"]
    assert "canConfirm" in schema["properties"]


def test_a_class_carries_the_subjects_its_teachers_named() -> None:
    rows = _read_rows(FOUR_SPELLINGS, OnboardingRowKind.STUDENT)
    rows += _read_rows(TEACHERS, OnboardingRowKind.TEACHER)

    derived = {item.normalised_name: item for item in _derived_classes(rows)}

    assert derived["jss 2a"].subjects == ["Basic Science", "Mathematics"]
    assert derived["jss 3b"].subjects == ["English Language"]


def test_the_subject_question_is_only_asked_where_it_can_be_argued_for() -> None:
    assert possible_pair("Maths", "Mathematics")
    assert possible_pair("Mathematic", "Mathematics")
    # Further Mathematics is a different subject, not a longer spelling.
    assert not possible_pair("Further Maths", "Mathematics")
    # A subject Nevo has never heard of is the school's own, accepted as
    # given, with no prompt. Nothing here claims a pair out of two names that
    # merely start alike.
    assert not possible_pair("Art", "Arithmetic")
    assert not possible_pair("Yoruba", "Igbo")
    assert not possible_pair("Quranic Recitation", "Quranic Studies")


def test_the_fuller_spelling_survives_a_same_answer() -> None:
    assert fuller("Maths", "Mathematics") == "Mathematics"
    assert fuller("Eng", "English Language") == "English Language"


def test_the_question_is_asked_on_the_classes_screen_and_not_at_onboarding() -> None:
    paths = app.openapi()["paths"]

    # A class merge changes the headcount and blocks payment; a subject
    # spelling does not, so it lives with the subjects and not the funnel.
    assert "/api/v1/subjects/spelling-questions" in paths
    assert not any("spelling" in path for path in paths if "onboarding" in path)


@pytest.mark.parametrize("path", ["/api/v1/onboarding/classes/merges"])
def test_the_merge_decision_is_a_route(path: str) -> None:
    assert path in app.openapi()["paths"]
