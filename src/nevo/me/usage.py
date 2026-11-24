"""How many lessons a /me learner has used this month, and the upload gate.

The gate sits at upload and nowhere else: one check, in one place, asking
whether this learner may start preparing one more lesson. Nothing after the
upload is metered - the cost is incurred at preparation.

Counted: the learner's own upload jobs started in the current allowance
period that did not fail. On the free tier the period is the calendar month
(Lagos time), because there is no purchase date. On a paid tier it is the
month that was bought, so the allowance resets on the purchase anniversary
(Lydia, ruling C, 24 November 2026): resetting paid tiers on the 1st would
give someone who buys on the 28th two allowances for one payment.

A re-upload Nevo serves from an earlier one makes no job and costs nothing.
A preparation that failed on Nevo's side is not the learner's to pay for.

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
        guardian_contact: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.usage = usage
        #: Where the consent request went, for "We sent [guardian email] a
        #: page to read" (Lydia's copy). None if nobody is named yet.
        self.guardian_contact = guardian_contact

    @property
    def upgrade_to(self) -> Tier | None:
        """The next tier up, for "[tier name] gives you [n] lessons a month"."""

        if self.usage is None or self.offer != "upgrade":
            return None
        bigger = [t for t in tiers.TIERS if t.lessons_per_month > self.usage.allowance]
        return min(bigger, key=lambda t: t.lessons_per_month) if bigger else None

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
    """The highest tier this learner holds a paid month of right now, or free."""

    from nevo.me.billing import subscription_for

    return (await subscription_for(session, user.id, now)).tier


async def usage_for(session: AsyncSession, user: User, now: datetime | None = None) -> Usage:
    from nevo.me.billing import current_purchase

    now = now or datetime.now(UTC)
    purchase = await current_purchase(session, user.id, now)
    if purchase is not None:
        tier = tiers.by_key(purchase.tier_key) or tiers.FREE
        start, end = purchase.period_start, purchase.period_end
    else:
        tier = tiers.FREE
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
    from nevo.consent.guardian import consent_view

    view = await consent_view(session, user)
    if "upload" in view.blocked:
        raise UploadRefused("upload_consent_required", guardian_contact=view.guardian_contact)
    usage = await usage_for(session, user, now)
    ceiling = get_settings().me_fair_use_ceiling
    effective = min(usage.allowance, ceiling) if ceiling is not None else usage.allowance
    if usage.used >= effective:
        raise UploadRefused("upload_allowance_exhausted", usage)
    return usage
