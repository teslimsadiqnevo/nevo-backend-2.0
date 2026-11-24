"""How many lessons a /me learner has used this month, and the upload gate.

The gate sits at upload and nowhere else: one check, in one place, asking
whether this learner may start preparing one more lesson. Nothing after the
upload is metered - the cost is incurred at preparation.

Counted: the learner's own upload jobs started this calendar month (Lagos
time) that did not fail. A re-upload Nevo serves from an earlier one makes no
job and costs nothing. A preparation that failed on Nevo's side is not the
learner's to pay for.

Two refusals, never one: consent outstanding and allowance exhausted have
different screens and different ways out (Yinka's contract point), so they
carry different codes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.consent.guardian import upload_blocked_by_consent
from nevo.core.config import get_settings
from nevo.db.models.account import User
from nevo.db.models.product import UploadJob
from nevo.me import tiers
from nevo.me.tiers import Tier

LAGOS = ZoneInfo("Africa/Lagos")


@dataclass(frozen=True)
class Usage:
    tier: Tier
    used: int
    allowance: int
    resets_at: datetime

    @property
    def remaining(self) -> int:
        return max(0, self.allowance - self.used)


class UploadRefused(Exception):
    def __init__(
        self,
        code: Literal["upload_consent_required", "upload_allowance_exhausted"],
        usage: Usage | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.usage = usage

    @property
    def offer(self) -> Literal["guardian_consent", "upgrade", "contact"]:
        if self.code == "upload_consent_required":
            return "guardian_consent"
        assert self.usage is not None
        return "contact" if self.usage.tier == tiers.TOP else "upgrade"


def month_window(now: datetime) -> tuple[datetime, datetime]:
    """The current calendar month in Lagos, as UTC bounds [start, end)."""

    local = now.astimezone(LAGOS)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(
        month=start.month + 1
    )
    return start.astimezone(UTC), end.astimezone(UTC)


async def current_tier(session: AsyncSession, user: User, now: datetime) -> Tier:
    """The tier this learner holds this month.

    Free until Phase 4 builds the month a learner buys through checkout; that
    record is what this reads then.
    """

    del session, user, now
    return tiers.FREE


async def usage_for(session: AsyncSession, user: User, now: datetime | None = None) -> Usage:
    now = now or datetime.now(UTC)
    start, end = month_window(now)
    used = await session.scalar(
        select(func.count())
        .select_from(UploadJob)
        .where(
            UploadJob.requested_by_id == user.id,
            UploadJob.school_id.is_(None),
            UploadJob.created_at >= start,
            UploadJob.created_at < end,
            UploadJob.status != "failed",
        )
    )
    tier = await current_tier(session, user, now)
    return Usage(tier=tier, used=int(used or 0), allowance=tier.lessons_per_month, resets_at=end)


async def require_upload_allowed(
    session: AsyncSession, user: User, now: datetime | None = None
) -> Usage:
    """Raise UploadRefused, or return the usage this upload is counted against.

    Holds a per-learner lock until the caller's transaction ends, so two
    uploads at once cannot both take the last lesson.
    """

    key = int.from_bytes(
        hashlib.sha256(f"me-upload:{user.id}".encode()).digest()[:8], "big", signed=True
    )
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    if await upload_blocked_by_consent(session, user):
        raise UploadRefused("upload_consent_required")
    usage = await usage_for(session, user, now)
    ceiling = get_settings().me_fair_use_ceiling
    effective = min(usage.allowance, ceiling) if ceiling is not None else usage.allowance
    if usage.used >= effective:
        raise UploadRefused("upload_allowance_exhausted", usage)
    return usage
