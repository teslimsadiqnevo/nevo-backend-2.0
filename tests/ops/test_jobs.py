"""Scheduled job runner tests."""
from datetime import UTC, datetime, timedelta

from nevo.db.models.scheduled_job import ScheduledJobRun
from nevo.ops.jobs import ScheduledJob, ScheduledJobRunner, advisory_lock_key

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


async def _noop() -> str:
    return "ok"


def _job(name: str = "test.job", hours: int = 24) -> ScheduledJob:
    return ScheduledJob(name=name, interval=timedelta(hours=hours), run=_noop)


def test_lock_keys_are_stable_and_distinct() -> None:
    assert advisory_lock_key("retention.anonymise") == advisory_lock_key("retention.anonymise")
    assert advisory_lock_key("retention.anonymise") != advisory_lock_key("sso.roster_sync")


def test_lock_keys_fit_a_signed_32_bit_integer() -> None:
    for name in ("retention.anonymise", "sso.roster_sync", "billing.collect_due_invoices"):
        assert 0 <= advisory_lock_key(name) <= 0x7FFFFFFF


def test_a_job_that_never_ran_is_due() -> None:
    record = ScheduledJobRun(job_name="test.job")

    assert ScheduledJobRunner._is_due(record, _job(), NOW)


def test_a_job_inside_its_interval_is_not_due() -> None:
    record = ScheduledJobRun(job_name="test.job")
    record.last_finished_at = NOW - timedelta(hours=1)

    assert not ScheduledJobRunner._is_due(record, _job(hours=24), NOW)


def test_a_job_past_its_interval_is_due() -> None:
    record = ScheduledJobRun(job_name="test.job")
    record.last_finished_at = NOW - timedelta(hours=25)

    assert ScheduledJobRunner._is_due(record, _job(hours=24), NOW)


def test_a_naive_last_run_is_treated_as_utc() -> None:
    record = ScheduledJobRun(job_name="test.job")
    record.last_finished_at = datetime(2026, 8, 30, 11, 0)

    assert ScheduledJobRunner._is_due(record, _job(hours=24), NOW)


def test_a_started_but_unfinished_job_still_counts_as_recent() -> None:
    """Otherwise a crashed run would be retried on every single sweep."""
    record = ScheduledJobRun(job_name="test.job")
    record.last_started_at = NOW - timedelta(minutes=5)

    assert not ScheduledJobRunner._is_due(record, _job(hours=24), NOW)
