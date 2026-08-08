import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime

from nevo.ops.ports import HeartbeatRepository

logger = logging.getLogger(__name__)


class HeartbeatLoop:
    """Writes one row per calendar day to keep the database active.

    Checks on a shorter cadence than 24h so a missed tick (deploy,
    restart, brief outage) doesn't skip a day; the write itself is
    idempotent via a unique constraint on beat_date, so re-checking
    within the same day is a harmless no-op.
    """

    def __init__(
        self,
        *,
        repository: HeartbeatRepository,
        check_interval_seconds: float,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._repository = repository
        self._check_interval_seconds = check_interval_seconds
        self._today = today or (lambda: datetime.now(UTC).date())
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(
            self._run(),
            name="heartbeat-loop",
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self._repository.record(self._today())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Heartbeat write failed", exc_info=True)
            await asyncio.sleep(self._check_interval_seconds)
