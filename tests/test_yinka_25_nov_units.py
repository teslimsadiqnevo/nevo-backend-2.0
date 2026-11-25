"""S15 from the frontend's 25 November list: every week, with zeros."""

from datetime import UTC, date, datetime, timedelta

from nevo.api.learning_support_records import every_week


def test_every_week_is_sent_with_zeros_and_starts_on_monday():
    now = datetime(2026, 11, 25, 12, tzinfo=UTC)
    weeks = every_week(now - timedelta(weeks=12), now, {date(2026, 11, 16): 3})

    assert [w.week_starting.weekday() for w in weeks] == [0] * len(weeks)
    assert weeks[0].week_starting == date(2026, 8, 31)
    assert weeks[-1].week_starting == date(2026, 11, 23)
    assert [w.count for w in weeks].count(0) == len(weeks) - 1
    assert next(w.count for w in weeks if w.week_starting == date(2026, 11, 16)) == 3
