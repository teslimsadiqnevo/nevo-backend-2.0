"""/me Phase 4: a bought month ends on the same day next month, clamped."""

from datetime import UTC, datetime

from nevo.me.billing import add_one_month
from nevo.me.references import is_individual_reference


def test_same_day_next_month() -> None:
    assert add_one_month(datetime(2026, 11, 24, 9, tzinfo=UTC)) == datetime(
        2026, 12, 24, 9, tzinfo=UTC
    )


def test_the_end_of_a_long_month_clamps() -> None:
    assert add_one_month(datetime(2027, 1, 31, tzinfo=UTC)) == datetime(2027, 2, 28, tzinfo=UTC)
    assert add_one_month(datetime(2028, 1, 31, tzinfo=UTC)) == datetime(2028, 2, 29, tzinfo=UTC)


def test_december_rolls_the_year() -> None:
    assert add_one_month(datetime(2026, 12, 15, tzinfo=UTC)) == datetime(2027, 1, 15, tzinfo=UTC)


def test_only_this_band_s_references_route_to_it() -> None:
    assert is_individual_reference("nevo-me-20261124-abc")
    assert not is_individual_reference("nevo-INV2026001-20261124-abc")
