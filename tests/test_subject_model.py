"""Subjects on the class and the teacher, and who teaches what. SCRUM-194.

Nevo had no idea what subject a class was taught or what a teacher taught. The
two facts this ticket adds are kept apart on purpose: a teacher's subjects are
what that person teaches, and an assignment names which of them she teaches to
which class.
"""

from __future__ import annotations

import inspect

import pytest

import nevo.db.models  # noqa: F401  (registers the tables)
from nevo.db.base import Base
from nevo.domain.subjects.vocabulary import (
    CANONICAL_SUBJECTS,
    SubjectOrigin,
    SubjectReviewState,
)
from nevo.main import app
from nevo.subjects.teacher_import import merge_rows, split_legacy


def test_everything_points_at_the_school_list_and_not_the_canonical_one() -> None:
    """The design decision the whole ticket rests on.

    A school's list holds a row per subject it uses however that subject
    arrived, so pointing a school's "Maths" row at canonical Mathematics later
    changes what the row resolves to and touches none of the records filed
    against it.
    """

    for table in ("class_subjects", "teacher_subjects"):
        columns = Base.metadata.tables[table].columns
        assert "school_subject_id" in columns
        assert "canonical_subject_id" not in columns

    assignments = Base.metadata.tables["teacher_class_assignments"].columns
    assert "school_subject_id" in assignments


def test_a_school_subject_can_be_repointed_without_losing_records() -> None:
    school_subjects = Base.metadata.tables["school_subjects"].columns

    # Nullable and settable later: that is what a merge is.
    assert school_subjects["canonical_subject_id"].nullable
    assert not school_subjects["school_id"].nullable


def test_one_school_cannot_hold_the_same_subject_twice() -> None:
    table = Base.metadata.tables["school_subjects"]
    names = {c.name for c in table.constraints if c.name}

    assert "uq_school_subjects_name" in names


def test_an_assignment_is_unique_per_subject_not_per_class() -> None:
    """A teacher teaching two subjects to one class is two assignments."""

    indexes = {index.name for index in Base.metadata.tables["teacher_class_assignments"].indexes}

    assert "uq_teacher_class_assignments_active_triple" in indexes
    assert "uq_teacher_class_assignments_active_pair" not in indexes


def test_the_canonical_list_is_seeded_by_migration_not_by_code() -> None:
    from pathlib import Path

    migration = Path("alembic/versions/20260929_0083_subjects.py").read_text()

    # So it can be extended or replaced without a deploy.
    assert "INSERT INTO canonical_subjects" in migration
    assert len(CANONICAL_SUBJECTS) > 20
    # Stable slugs, because reports point at those and display names change.
    assert all(slug == slug.lower() for slug, _ in CANONICAL_SUBJECTS)
    assert len({slug for slug, _ in CANONICAL_SUBJECTS}) == len(CANONICAL_SUBJECTS)


def test_a_school_addition_lands_in_review_and_a_canonical_one_does_not() -> None:
    source = inspect.getsource(__import__("nevo.subjects.resolution", fromlist=["ensure"]).ensure)

    assert "SubjectReviewState.PENDING" in source
    assert "SubjectReviewState.MERGED" in source
    assert SubjectOrigin.SCHOOL in set(SubjectOrigin)
    assert SubjectReviewState.KEPT in set(SubjectReviewState)


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("Mathematics", ["Mathematics"]),
        # Semicolons, not commas: a comma inside a cell breaks the file for
        # anyone editing it in Excel, which is everyone. SCRUM-203.
        ("Maths; Physics", ["Maths", "Physics"]),
        ("Mathematics / Further Mathematics", ["Mathematics", "Further Mathematics"]),
        ("", []),
        ("Maths; Maths", ["Maths"]),
    ],
)
def test_a_legacy_cell_is_split_on_semicolons(cell: str, expected: list[str]) -> None:
    assert split_legacy(cell) == expected


def test_a_comma_is_not_a_separator() -> None:
    """Row-per-assignment needs none, and a comma breaks the CSV."""

    assert split_legacy("Mathematics, Further Mathematics") == ["Mathematics, Further Mathematics"]


def test_teacher_rows_merge_on_email_and_never_on_name() -> None:
    merged = merge_rows(
        [
            (
                2,
                {
                    "email": "B.Bello@x.com",
                    "first_name": "Bisi",
                    "last_name": "Bello",
                    "subject": "Mathematics",
                    "class": "JSS 1A",
                },
            ),
            (
                3,
                {
                    "email": "b.bello@x.com",
                    "first_name": "B",
                    "last_name": "Bello",
                    "subject": "Further Mathematics",
                    "class": "SS 1",
                },
            ),
            (
                4,
                {
                    "email": "other@x.com",
                    "first_name": "Bisi",
                    "last_name": "Bello",
                    "subject": "Mathematics",
                    "class": "JSS 1A",
                },
            ),
        ]
    )

    by_email = {teacher.email: teacher for teacher in merged}
    # Same address twice is one teacher holding both assignments.
    assert len(merged) == 2
    assert by_email["b.bello@x.com"].subjects == ["Mathematics", "Further Mathematics"]
    assert by_email["b.bello@x.com"].row_numbers == [2, 3]
    # Two Mrs Bellos with different addresses stay two people.
    assert by_email["other@x.com"].subjects == ["Mathematics"]


def test_one_row_is_one_assignment_and_nothing_is_cross_multiplied() -> None:
    """The failure this shape exists to prevent. SCRUM-203.

    Two subjects against two classes as lists would produce four pairs, two of
    which nobody teaches. Row per assignment produces exactly what was written.
    """

    merged = merge_rows(
        [
            (
                2,
                {
                    "email": "a@x.com",
                    "first_name": "Bisi",
                    "last_name": "Bello",
                    "subject": "Mathematics",
                    "class": "JSS 2A",
                },
            ),
            (
                3,
                {
                    "email": "a@x.com",
                    "first_name": "Bisi",
                    "last_name": "Bello",
                    "subject": "Further Mathematics",
                    "class": "SS 1",
                },
            ),
        ]
    )

    pairs = {(a.subject, a.class_name) for a in merged[0].assignments}
    assert pairs == {("Mathematics", "JSS 2A"), ("Further Mathematics", "SS 1")}
    # Never these.
    assert ("Further Mathematics", "JSS 2A") not in pairs
    assert ("Mathematics", "SS 1") not in pairs


def test_a_row_with_no_class_is_not_an_assignment() -> None:
    merged = merge_rows(
        [
            (
                2,
                {
                    "email": "a@x.com",
                    "first_name": "A",
                    "last_name": "B",
                    "subject": "Mathematics",
                    "class": "",
                },
            )
        ]
    )

    assert merged[0].assignments == []


def test_the_first_spelling_of_a_name_wins() -> None:
    merged = merge_rows(
        [
            (
                2,
                {
                    "email": "a@x.com",
                    "first_name": "Bisi",
                    "last_name": "Bello",
                    "subject": "Maths",
                    "class": "JSS 1A",
                },
            ),
            (
                3,
                {
                    "email": "a@x.com",
                    "first_name": "B",
                    "last_name": "Bello",
                    "subject": "Maths",
                    "class": "JSS 1A",
                },
            ),
        ]
    )

    # Taking the last one means the answer depends on row order.
    assert merged[0].first_name == "Bisi"


def test_a_row_with_no_email_cannot_be_merged_at_all() -> None:
    # It is rejected upstream by row number; nothing here can identify it.
    assert merge_rows([(2, {"email": "", "first_name": "Bisi", "subject": "Maths"})]) == []


def test_the_teacher_template_asks_for_subjects_and_requires_an_email() -> None:
    from nevo.api.onboarding import REQUIRED_TEACHER_COLUMNS, TEACHER_COLUMNS

    # Singular, and required: one row is one thing a teacher teaches, so a row
    # without a subject or a class is not an assignment. SCRUM-203.
    assert "subject" in TEACHER_COLUMNS
    assert "class" in TEACHER_COLUMNS
    assert "email" in REQUIRED_TEACHER_COLUMNS
    assert "subject" in REQUIRED_TEACHER_COLUMNS


def test_the_validity_rule_refuses_rather_than_widening_either_list() -> None:
    from nevo.teacher_assignments.repositories import (
        SqlAlchemyTeacherAssignmentRepository,
    )

    source = inspect.getsource(SqlAlchemyTeacherAssignmentRepository._require_subject_on_both)

    assert "SubjectRequiredError" in source
    assert "SubjectNotOnTeacherError" in source
    assert "SubjectNotOnClassError" in source
    # Nothing is created here. A missing subject is a setup gap for the school.
    assert "session.add" not in source


def test_the_three_refusals_are_told_apart_on_the_wire() -> None:
    described = app.openapi()["paths"]["/api/v1/teacher-class-assignments"]["post"]["responses"]

    assert "422" in described
    for code in ("subject_required", "subject_not_on_teacher", "subject_not_on_class"):
        assert code in described["422"]["description"]


def test_a_school_can_see_and_add_its_own_subjects() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/subjects" in paths
    assert "/api/v1/subjects/canonical" in paths
    # Writes nothing: the import confirmation step needs to preview.
    assert "/api/v1/subjects/resolve" in paths
    assert "/api/v1/teachers/{teacher_id}/subjects" in paths
