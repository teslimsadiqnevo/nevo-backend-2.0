"""The template and the parser cannot disagree. SCRUM-199.

This is the ticket's stated point, so it is the first test here. If the front
end holds the header row then the day a column changes the template and the
parser drift, and a school downloads a file that its own upload rejects - with
nothing to notice it until a proprietor hits it during onboarding.

That is not hypothetical. The drawn templates carried "Full name" as one column
and "Class(es)" with brackets; the importer wanted first and last separately and
"class" singular, and it would have answered 400 missing_columns on a file a
school filled in exactly as instructed.
"""

from __future__ import annotations

import inspect

from nevo.api.import_templates import (
    CLASS_COLUMNS,
    EXAMPLE_DATE,
    EXAMPLE_MARKER,
    HEADINGS,
    download_template,
    heading,
)
from nevo.api.onboarding import (
    REQUIRED_STUDENT_COLUMNS,
    REQUIRED_TEACHER_COLUMNS,
    STUDENT_COLUMNS,
    TEACHER_COLUMNS,
    _column,
)
from nevo.main import app


def test_every_parser_column_has_a_template_column_and_the_reverse() -> None:
    """The test the ticket exists for.

    The template is generated from these same tuples, so the only way they can
    drift is if somebody writes a header by hand. This fails if they do.
    """

    source = inspect.getsource(download_template)

    assert "STUDENT_COLUMNS" in source
    assert "TEACHER_COLUMNS" in source
    assert "CLASS_COLUMNS" in source
    # No literal header row anywhere in the generator.
    for handwritten in ('"First name"', '"Parent email"', '"Full name"'):
        assert handwritten not in source


def test_every_column_has_a_readable_heading() -> None:
    """A school should not be shown parser_snake_case."""

    for column in (*STUDENT_COLUMNS, *TEACHER_COLUMNS, *CLASS_COLUMNS):
        assert column in HEADINGS, column
        assert "_" not in HEADINGS[column]


def test_a_readable_heading_folds_back_to_the_column_the_parser_wants() -> None:
    """The round trip that makes the generated file importable at all."""

    for column in (*STUDENT_COLUMNS, *TEACHER_COLUMNS):
        assert _column(heading(column)) == column


def test_the_headers_the_drawn_templates_used_now_resolve() -> None:
    """Two of the three are tolerable; one genuinely is not.

    "Class(es)" and "Surname" are words a school writes, and rejecting a file
    over them is our problem rather than theirs, so they now fold to the right
    column. "Full name" cannot be rescued: it is one value where the parser
    needs two, and splitting a Nigerian name on a space guesses wrong often
    enough to matter.
    """

    assert _column("Class(es)") in TEACHER_COLUMNS
    assert _column("Surname") in STUDENT_COLUMNS
    assert _column("Class") in TEACHER_COLUMNS
    assert _column("Full name") not in STUDENT_COLUMNS


def test_the_required_columns_are_a_subset_of_the_template() -> None:
    assert set(REQUIRED_STUDENT_COLUMNS) <= set(STUDENT_COLUMNS)
    assert set(REQUIRED_TEACHER_COLUMNS) <= set(TEACHER_COLUMNS)


def test_the_student_template_keeps_what_it_cannot_do_without() -> None:
    # Age is derived from the date of birth; activation depends on the guardian
    # email reaching somebody; and without an admission number the child cannot
    # identify themselves at the door or be matched on a re-upload.
    for column in ("date_of_birth", "guardian_email", "admission_number", "class"):
        assert column in REQUIRED_STUDENT_COLUMNS, column


def test_a_guardian_name_is_asked_for_and_not_insisted_on() -> None:
    assert "guardian_first_name" in STUDENT_COLUMNS
    assert "guardian_last_name" in STUDENT_COLUMNS
    assert "guardian_relationship" in STUDENT_COLUMNS
    for optional in ("guardian_first_name", "guardian_last_name", "guardian_relationship"):
        assert optional not in REQUIRED_STUDENT_COLUMNS, optional


def test_a_column_the_template_does_not_insist_on_is_an_optional_header() -> None:
    """Last term's copy of the template still imports.

    Refusing a file for a header we ourselves made optional is the same drift
    this ticket prevents, arriving from the other direction.
    """

    import inspect

    from nevo.api.onboarding import _read_rows

    source = inspect.getsource(_read_rows)

    assert "_required(kind)" in source
    assert "for column in STUDENT_COLUMNS" not in source


def test_the_teacher_template_is_one_row_per_assignment() -> None:
    # Singular subject, plus the class it is taught to. A row missing either is
    # not an assignment. SCRUM-203.
    assert "subject" in TEACHER_COLUMNS
    assert "class" in TEACHER_COLUMNS
    assert "subjects" not in TEACHER_COLUMNS
    for column in ("email", "subject", "class"):
        assert column in REQUIRED_TEACHER_COLUMNS, column


def test_the_example_demonstrates_exactly_one_date_format() -> None:
    """The parser reads four. A template that shows four gets a mixture."""

    from nevo.api.onboarding import _parse_date

    assert _parse_date(EXAMPLE_DATE) is not None
    assert EXAMPLE_DATE.count("-") == 2
    assert "/" not in EXAMPLE_DATE


def test_the_example_row_is_marked_for_deletion() -> None:
    # Schools upload it as a real record otherwise.
    assert "DELETE" in EXAMPLE_MARKER.upper()
    assert "EXAMPLE" in EXAMPLE_MARKER.upper()


def test_the_teacher_example_repeats_one_teacher_rather_than_listing() -> None:
    source = inspect.getsource(download_template)

    # Three rows, one teacher. A list of subjects against a list of classes
    # cross multiplies wrongly, so the template never demonstrates one.
    assert source.count("bisi.bello@example.com") == 3
    assert "which are one teacher" in source


def test_the_examples_use_the_school_own_words() -> None:
    source = inspect.getsource(download_template)

    # An invented example gets copied literally, and then a school has a class
    # it never taught.
    assert "_example_class_names" in source
    assert "_example_subjects" in source


def test_all_three_templates_are_downloadable() -> None:
    operation = app.openapi()["paths"]["/api/v1/onboarding/templates/{template}"]["get"]
    values = operation["parameters"][0]["schema"]["enum"]

    assert set(values) == {"students", "teachers", "classes"}
