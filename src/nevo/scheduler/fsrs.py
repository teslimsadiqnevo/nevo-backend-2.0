from datetime import datetime, timedelta

from nevo.scheduler.entities import ConceptSchedule

FSRS_ALPHA = 1.0
FSRS_BETA = 1.0
REVIEW_THRESHOLD = 0.85
INITIAL_SUCCESS_STABILITY_DAYS = 10.0
INITIAL_FAILURE_STABILITY_DAYS = 3.0
INITIAL_DIFFICULTY = 5.0


def retrievability(
    *,
    elapsed_days: float,
    stability: float,
    alpha: float = FSRS_ALPHA,
    beta: float = FSRS_BETA,
) -> float:
    stability = max(stability, 0.1)
    elapsed_days = max(elapsed_days, 0)
    return (1 + alpha * elapsed_days / stability) ** (-beta)


def days_until_review_due(
    *,
    stability: float,
    threshold: float = REVIEW_THRESHOLD,
    alpha: float = FSRS_ALPHA,
    beta: float = FSRS_BETA,
) -> float:
    stability = max(stability, 0.1)
    threshold = min(max(threshold, 0.01), 0.99)
    alpha = max(alpha, 0.01)
    beta = max(beta, 0.01)
    return stability / alpha * (threshold ** (-1 / beta) - 1)


def next_review_due(*, reviewed_at: datetime, stability: float) -> datetime:
    return reviewed_at + timedelta(days=days_until_review_due(stability=stability))


def initial_schedule(
    *,
    student_id,
    concept_id,
    recall_successful: bool,
    reviewed_at: datetime,
) -> ConceptSchedule:
    stability = (
        INITIAL_SUCCESS_STABILITY_DAYS
        if recall_successful
        else INITIAL_FAILURE_STABILITY_DAYS
    )
    difficulty = INITIAL_DIFFICULTY - 0.5 if recall_successful else INITIAL_DIFFICULTY + 1
    return _schedule(
        student_id=student_id,
        concept_id=concept_id,
        stability=stability,
        difficulty=difficulty,
        review_count=1,
        reviewed_at=reviewed_at,
    )


def update_schedule(
    *,
    current: ConceptSchedule,
    recall_successful: bool,
    reviewed_at: datetime,
) -> ConceptSchedule:
    if recall_successful:
        stability_gain = 1.35 + max(0, 10 - current.difficulty) * 0.05
        stability = current.stability * stability_gain + 1.0
        difficulty = current.difficulty - 0.25
    else:
        stability = max(0.5, current.stability * 0.55)
        difficulty = current.difficulty + 0.75
    return _schedule(
        student_id=current.student_id,
        concept_id=current.concept_id,
        stability=stability,
        difficulty=difficulty,
        review_count=current.review_count + 1,
        reviewed_at=reviewed_at,
    )


def refresh_due_date(
    *,
    current: ConceptSchedule,
    now: datetime,
) -> ConceptSchedule:
    return ConceptSchedule(
        student_id=current.student_id,
        concept_id=current.concept_id,
        stability=current.stability,
        difficulty=current.difficulty,
        retrievability=retrievability(
            elapsed_days=(now - current.last_review).total_seconds() / 86_400,
            stability=current.stability,
        ),
        last_review=current.last_review,
        review_count=current.review_count,
        next_review_due=next_review_due(
            reviewed_at=current.last_review,
            stability=current.stability,
        ),
    )


def _schedule(
    *,
    student_id,
    concept_id,
    stability: float,
    difficulty: float,
    review_count: int,
    reviewed_at: datetime,
) -> ConceptSchedule:
    stability = round(max(stability, 0.1), 6)
    difficulty = round(min(max(difficulty, 1.0), 10.0), 6)
    return ConceptSchedule(
        student_id=student_id,
        concept_id=concept_id,
        stability=stability,
        difficulty=difficulty,
        retrievability=1.0,
        last_review=reviewed_at,
        review_count=review_count,
        next_review_due=next_review_due(
            reviewed_at=reviewed_at,
            stability=stability,
        ),
    )
