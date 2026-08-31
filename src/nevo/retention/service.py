from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import School, User
from nevo.domain.accounts.vocabulary import UserRole, UserStatus
from nevo.retention.anonymisation import anonymise_student

DEFAULT_BATCH_SIZE = 200


@dataclass(frozen=True, slots=True)
class RetentionSweepResult:
    scanned: int
    anonymised: int

    def summary(self) -> str:
        return f"anonymised {self.anonymised} of {self.scanned} expired student records"


class RetentionService:
    """Enforces each school's data-retention window without an admin acting.

    A student who left the school is anonymised once their school's
    ``data_retention_days`` have elapsed since deactivation. Already-anonymised
    rows are skipped, so the sweep is safe to run as often as you like.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def sweep(
        self,
        *,
        now: datetime | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> RetentionSweepResult:
        current_time = now or datetime.now(UTC)
        async with self._sessions.begin() as session:
            rows = (
                await session.execute(
                    select(User, School.data_retention_days)
                    .join(School, School.id == User.school_id)
                    .where(
                        User.role == UserRole.STUDENT,
                        User.status == UserStatus.DEACTIVATED,
                        User.deactivated_at.is_not(None),
                        User.anonymised_at.is_(None),
                    )
                    .order_by(User.deactivated_at)
                    .limit(batch_size)
                    .with_for_update(of=User, skip_locked=True)
                )
            ).all()

            anonymised = 0
            for student, retention_days in rows:
                if self._is_expired(student.deactivated_at, retention_days, current_time):
                    anonymise_student(student, now=current_time)
                    anonymised += 1
        return RetentionSweepResult(scanned=len(rows), anonymised=anonymised)

    @staticmethod
    def _is_expired(
        deactivated_at: datetime | None,
        retention_days: int,
        now: datetime,
    ) -> bool:
        if deactivated_at is None:
            return False
        if deactivated_at.tzinfo is None:
            deactivated_at = deactivated_at.replace(tzinfo=UTC)
        return now - deactivated_at >= timedelta(days=retention_days)
