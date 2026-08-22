from datetime import UTC, datetime, timedelta
from uuid import uuid4

from nevo.scheduler.fsrs import (
    days_until_review_due,
    initial_schedule,
    retrievability,
    update_schedule,
)


def test_retrievability_uses_fsrs_formula() -> None:
    assert retrievability(elapsed_days=2, stability=8) == 0.8


def test_successful_first_review_schedules_roughly_one_to_three_days_later() -> None:
    reviewed_at = datetime(2026, 8, 22, tzinfo=UTC)
    schedule = initial_schedule(
        student_id=uuid4(),
        concept_id=uuid4(),
        recall_successful=True,
        reviewed_at=reviewed_at,
    )

    delay = schedule.next_review_due - reviewed_at
    assert timedelta(days=1) <= delay <= timedelta(days=3)
    assert schedule.stability > 0
    assert schedule.review_count == 1


def test_successful_recall_increases_stability_and_failure_decreases_it() -> None:
    reviewed_at = datetime(2026, 8, 22, tzinfo=UTC)
    current = initial_schedule(
        student_id=uuid4(),
        concept_id=uuid4(),
        recall_successful=True,
        reviewed_at=reviewed_at,
    )

    successful = update_schedule(
        current=current,
        recall_successful=True,
        reviewed_at=reviewed_at + timedelta(days=2),
    )
    unsuccessful = update_schedule(
        current=current,
        recall_successful=False,
        reviewed_at=reviewed_at + timedelta(days=2),
    )

    assert successful.stability > current.stability
    assert unsuccessful.stability < current.stability
    assert successful.difficulty < current.difficulty
    assert unsuccessful.difficulty > current.difficulty


def test_due_day_calculation_crosses_retrievability_threshold() -> None:
    days = days_until_review_due(stability=10)

    assert retrievability(elapsed_days=days, stability=10) == 0.85
