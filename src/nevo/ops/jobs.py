import asyncio
import logging
import zlib
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.scheduled_job import ScheduledJobRun

logger = logging.getLogger(__name__)

ADVISORY_LOCK_NAMESPACE = 0x4E45_564F
"""Distinguishes Nevo's advisory locks from anything else on the database."""


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    """A recurring background task.

    ``run`` returns a short human-readable summary that lands on the job's
    last-run row, so an operator can see what the last execution actually did.
    """

    name: str
    interval: timedelta
    run: Callable[[], Awaitable[str]]


def advisory_lock_key(job_name: str) -> int:
    """A stable 32-bit key per job, for pg_try_advisory_lock."""
    return zlib.crc32(job_name.encode()) & 0x7FFF_FFFF


class ScheduledJobRunner:
    """Runs due jobs, at most one instance of each at a time.

    Concurrency is settled by a Postgres session-level advisory lock rather
    than by hoping only one process is up: a second web instance attempting
    the same job fails to take the lock and skips. That makes the schedule
    safe to leave running on every instance of a horizontally scaled
    deployment.
    """

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        jobs: tuple[ScheduledJob, ...],
        poll_seconds: float = 900,
    ) -> None:
        self._sessions = sessions
        self._jobs = jobs
        self._poll_seconds = poll_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None and self._jobs:
            self._task = asyncio.create_task(self._loop(), name="scheduled-jobs")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_due_jobs(self) -> dict[str, str]:
        """Run every job whose interval has elapsed. Returns name -> summary."""
        results: dict[str, str] = {}
        for job in self._jobs:
            summary = await self.run_job(job)
            if summary is not None:
                results[job.name] = summary
        return results

    async def run_job(self, job: ScheduledJob, *, force: bool = False) -> str | None:
        """Run one job if it is due and no other instance holds its lock."""
        async with self._sessions() as session:
            if not await self._claim(session, job, force=force):
                return None
            try:
                summary = await job.run()
            except Exception as error:
                logger.exception("Scheduled job %s failed", job.name)
                await self._finish(session, job, status="failed", error=str(error)[:1000])
                return None
            await self._finish(session, job, status="succeeded", summary=summary[:1000])
            return summary

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_due_jobs()
            except Exception:
                logger.exception("Scheduled job sweep failed")
            await asyncio.sleep(self._poll_seconds)

    async def _claim(
        self,
        session: AsyncSession,
        job: ScheduledJob,
        *,
        force: bool,
    ) -> bool:
        now = datetime.now(UTC)
        await session.execute(
            insert(ScheduledJobRun)
            .values(job_name=job.name)
            .on_conflict_do_nothing(constraint="uq_scheduled_job_runs_job_name")
        )
        await session.commit()

        locked = await session.scalar(
            text("SELECT pg_try_advisory_lock(:namespace, :key)").bindparams(
                namespace=ADVISORY_LOCK_NAMESPACE,
                key=advisory_lock_key(job.name),
            )
        )
        if not locked:
            return False

        record = await session.scalar(
            select(ScheduledJobRun).where(ScheduledJobRun.job_name == job.name)
        )
        due = force or record is None or self._is_due(record, job, now)
        if not due:
            await self._release(session, job)
            return False
        if record is not None:
            record.last_started_at = now
            record.last_status = "running"
        await session.commit()
        return True

    @staticmethod
    def _is_due(record: ScheduledJobRun, job: ScheduledJob, now: datetime) -> bool:
        last = record.last_finished_at or record.last_started_at
        if last is None:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return now - last >= job.interval

    async def _finish(
        self,
        session: AsyncSession,
        job: ScheduledJob,
        *,
        status: str,
        summary: str | None = None,
        error: str | None = None,
    ) -> None:
        try:
            record = await session.scalar(
                select(ScheduledJobRun).where(ScheduledJobRun.job_name == job.name)
            )
            if record is not None:
                record.last_finished_at = datetime.now(UTC)
                record.last_status = status
                record.last_summary = summary
                record.last_error = error
                record.run_count += 1
            await session.commit()
        finally:
            await self._release(session, job)

    @staticmethod
    async def _release(session: AsyncSession, job: ScheduledJob) -> None:
        await session.execute(
            text("SELECT pg_advisory_unlock(:namespace, :key)").bindparams(
                namespace=ADVISORY_LOCK_NAMESPACE,
                key=advisory_lock_key(job.name),
            )
        )
        await session.commit()
