"""Reports by year group, with a withheld figure that says so.

T17. Lydia, 20 November: a head teacher asking where the school is weakest
gets nothing from one whole-school number and cannot hold twenty classes in
their head. A year group is the grain between the two. And where the floor
hides a figure it must read as "too few to report" - not a blank, which reads
as nothing happened, and not a zero, which reads as a result. A head teacher
comparing year groups would act on either.

The floor does more work at this grain than at a whole school, which is why
it is tested at the boundary rather than merely applied.
"""

from __future__ import annotations

import inspect

from nevo.api import transformation_metrics as metrics
from nevo.api.transformation_metrics import (
    REPORTING_FLOOR,
    WITHHELD_LABEL,
    TransformationMetrics,
)


def test_a_year_group_is_a_scope() -> None:
    scope = TransformationMetrics.model_fields["scope"]
    assert "year_group" in str(scope.annotation)


def test_a_year_group_is_named_not_identified() -> None:
    """There is no year_groups table, only the label a school wrote on each
    class, so the scope id is null and the label carries the meaning."""
    assert TransformationMetrics.model_fields["scope_id"].annotation is not None
    assert "None" in str(TransformationMetrics.model_fields["scope_id"].annotation)
    assert "year_group" in TransformationMetrics.model_fields


def test_a_withheld_figure_says_too_few_to_report() -> None:
    assert WITHHELD_LABEL == "Too few to report"
    field = TransformationMetrics.model_fields["withheld_label"]
    assert field.alias == "withheldLabel"
    # Null when nothing is withheld, so a chart cannot print it by accident.
    assert field.default is None


def test_the_label_is_only_set_where_a_figure_is_withheld() -> None:
    source = inspect.getsource(metrics._metrics)
    suppressed_at = source.index("suppressed=True")
    unsuppressed_at = source.index("suppressed=False")
    label_at = source.index("withheld_label=WITHHELD_LABEL")
    assert suppressed_at < label_at < unsuppressed_at


def test_the_floor_still_applies_at_this_grain() -> None:
    """A year group with one class of four is below it."""
    assert REPORTING_FLOOR == 5
    source = inspect.getsource(metrics._metrics)
    assert "len(learners) < REPORTING_FLOOR" in source


def test_a_year_group_label_is_matched_without_punishing_spacing() -> None:
    '"JSS 1" and "jss 1 " are one year group to everybody but a comparison.'
    source = inspect.getsource(metrics.year_group_metrics)
    assert "casefold()" in source
    assert "func.btrim(Class.year_group)" in source
    assert 'year_group.split()' in source


def test_it_cannot_read_another_schools_year_group() -> None:
    source = inspect.getsource(metrics.year_group_metrics)
    assert "require_school_actor" in source
    assert "Class.school_id == actor.school_id" in source


def test_an_archived_class_is_not_counted_into_a_year_group() -> None:
    source = inspect.getsource(metrics.year_group_metrics)
    assert "Class.archived_at.is_(None)" in source


def test_an_empty_label_is_not_a_year_group() -> None:
    source = inspect.getsource(metrics.year_group_metrics)
    assert "if not label:" in source
