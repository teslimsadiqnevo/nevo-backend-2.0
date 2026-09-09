from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from nevo.consent.entities import ParentChildView
from nevo.consent.service import ConsentService
from nevo.parents.entities import GrowthNarrative
from nevo.parents.errors import ChildNotLinkedError
from nevo.parents.narrative import compose, headline_and_summary
from nevo.parents.repositories import SqlAlchemyParentInsightRepository

WINDOW_DAYS = 90
"""A term-length window.

The roster holds no term dates, so this is a fixed span rather than a real
term. The response carries the dates it actually used, so a screen can say
what it compared instead of claiming a term boundary we do not have.
"""


class ParentInsightService:
    """What a signed-in parent may read about their own child."""

    def __init__(
        self,
        *,
        repository: SqlAlchemyParentInsightRepository,
        consent: ConsentService,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._consent = consent
        self._now = now or (lambda: datetime.now(UTC))

    async def children(self, parent_id: UUID) -> list[ParentChildView]:
        return await self._consent.children_for_parent(parent_id)

    async def growth(
        self,
        *,
        parent_id: UUID,
        student_id: UUID,
    ) -> GrowthNarrative:
        children = await self._consent.children_for_parent(parent_id)
        child = next(
            (item for item in children if item.student_id == student_id),
            None,
        )
        if child is None:
            # The link table is the only authority on this. A parent asking
            # about a learner who is not theirs is refused before any signal
            # is read, not after.
            raise ChildNotLinkedError

        today = self._now().date()
        period_start = today - timedelta(days=WINDOW_DAYS)
        comparison_start = period_start - timedelta(days=WINDOW_DAYS)
        current = await self._repository.growth_signals(
            student_id=student_id,
            window_start=period_start,
            window_end=today,
        )
        previous = await self._repository.growth_signals(
            student_id=student_id,
            window_start=comparison_start,
            window_end=period_start - timedelta(days=1),
        )
        # Lower case on purpose: it has to read correctly mid-sentence, and
        # the prose lifts the first letter where one is needed.
        name = (child.first_name or "").strip() or "your child"
        statements = compose(name=name, current=current, previous=previous)
        headline, summary = headline_and_summary(name=name, statements=statements)
        return GrowthNarrative(
            student_id=student_id,
            student_first_name=name,
            headline=headline,
            summary=summary,
            statements=statements,
            period_start=period_start,
            period_end=today,
            comparison_start=comparison_start,
            comparison_end=period_start - timedelta(days=1),
            generated_at=self._now(),
        )


def window_bounds(today: date) -> tuple[date, date]:
    return today - timedelta(days=WINDOW_DAYS), today
