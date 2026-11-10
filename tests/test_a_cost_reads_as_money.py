"""A cost never reaches a teacher in scientific notation.

str() on a Decimal uses exponent notation whenever that is shorter, so a zero
cost quantised to eight places came out as "0E-8" and a console rendered it.
Decimal keeps the arithmetic exact; only the spelling changes.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from nevo.api.lesson_review import money


def test_the_reported_fault() -> None:
    assert money(Decimal("0").scaleb(-8)) == "0.00"


@pytest.mark.parametrize(
    "value", [Decimal("0"), Decimal("0.00"), Decimal("0E-8"), Decimal("-0"), 0, None, ""]
)
def test_nothing_spent_reads_as_nothing_spent(value) -> None:
    assert money(value) == "0.00"


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("1.23456789"), "1.23456789"),
        (Decimal("0.00000123"), "0.00000123"),
        (Decimal("0.5"), "0.50"),
        (Decimal("12"), "12.00"),
        (Decimal("12.00000000"), "12.00"),
        (Decimal("0.07"), "0.07"),
    ],
)
def test_a_real_cost_keeps_its_value_and_reads_as_money(value, expected) -> None:
    assert money(value) == expected
    assert Decimal(money(value)) == value


@pytest.mark.parametrize(
    "value",
    [
        Decimal("0.00000001"),
        Decimal("123456.78901234"),
        Decimal("0.000000001"),
        Decimal("1E-10"),
        Decimal("1E+4"),
    ],
)
def test_no_exponent_ever_survives(value) -> None:
    out = money(value)
    assert "E" not in out.upper(), out
    assert Decimal(out) == value, "trimming changed the amount"


def test_a_value_that_is_not_a_number_does_not_raise() -> None:
    """A cost column is nullable and a console must still render the row."""
    assert money("rubbish") == "0.00"
    assert money(object()) == "0.00"


def test_precision_is_not_lost_on_a_sub_penny_cost() -> None:
    """These are fractions of a cent per call; rounding to pennies hides them."""
    assert money(Decimal("0.00004200")) == "0.000042"
    assert Decimal(money(Decimal("0.00004200"))) == Decimal("0.000042")


def test_both_report_sites_use_it() -> None:
    from nevo.api import lesson_review

    source = lesson_review.__loader__.get_source(lesson_review.__name__)
    assert "estimated_cost_usd=money(" in source
    assert "estimated_cost_usd=str(" not in source
