"""T11's fields, and the query shape they are allowed to have.

Four were asked for. Three are here: the term, the class names a lesson is
assigned to, and the source's page total. The fourth - a per-class finished
count and opened time - has no endpoint to live on, and inventing one would
be guessing at what the screen does.

The constraint these were built under matters as much as the fields. At
~280ms a round trip from the dyno to Frankfurt, a per-item lookup on a list
endpoint is the difference between slow and unusable: the classes list once
issued eighty-one queries to render forty classes. So each of these is one
query for the whole page, and that is what the tests check.
"""

from __future__ import annotations

import inspect

from nevo.api import product_admin, product_learning
from nevo.api.response_models import (
    ClassSummaryResponse,
    LessonSummaryResponse,
    UploadStructureDocument,
)
from nevo.content_parsing.service import _source_page_total


def test_a_class_says_which_term_it_is() -> None:
    assert "term" in ClassSummaryResponse.model_fields
    assert ClassSummaryResponse.model_fields["term"].default is None


def test_the_term_is_fetched_once_for_the_whole_page() -> None:
    """Not once per class. This route already learned that at 81 queries."""
    source = inspect.getsource(product_admin.list_classes)
    assert source.count("_current_term_label(") == 1
    # Outside the loop that builds each row. Matched on the statement, not
    # on "for item in classes", which also appears in an earlier
    # comprehension collecting the ids.
    row_loop = "\n    for item in classes:"
    assert row_loop in source
    assert source.index("_current_term_label(") < source.index(row_loop)


def test_the_detail_route_answers_with_the_same_fields_as_the_list() -> None:
    """It answered with neither section nor session, so a detail view read as
    a class with no year while the list beside it showed one."""
    source = inspect.getsource(product_admin.class_detail)
    for field in ('"section"', '"academicSession"', '"term"'):
        assert field in source


def test_a_lesson_says_which_classes_it_is_assigned_to() -> None:
    assert "class_names" in LessonSummaryResponse.model_fields


def test_class_names_are_one_grouped_query_not_one_per_lesson() -> None:
    source = inspect.getsource(product_learning._class_names_by_lesson)
    assert "lesson_id.in_(lesson_ids)" in source
    assert "group_by" not in source or "distinct" in source
    # An empty page must not issue a query with an empty IN list.
    assert "if not lesson_ids:" in source
    listing = inspect.getsource(product_learning.lessons)
    assert listing.count("_class_names_by_lesson(") == 1


def test_cancelled_assignments_do_not_name_a_class() -> None:
    """The count beside it already excludes them, so these must agree."""
    source = inspect.getsource(product_learning._class_names_by_lesson)
    assert 'status != "cancelled"' in source


def test_an_upload_says_how_many_pages_the_source_had() -> None:
    field = UploadStructureDocument.model_fields["page_total"]
    assert field.alias == "pageTotal"
    assert field.default is None


def test_the_page_total_comes_from_the_markers_already_in_the_source() -> None:
    """Nothing new stored: the extractor writes [Page N] into the text."""
    assert _source_page_total("[Page 1]\na\n[Page 2]\nb\n[Page 9]\nc") == 9


def test_pasted_text_has_no_page_count_rather_than_one() -> None:
    """A source with no pages honestly has no page total, and claiming 1
    would make "1 of 1" appear on something that was never paginated."""
    assert _source_page_total("just some pasted text") is None
    assert _source_page_total("") is None
    assert _source_page_total(None) is None
