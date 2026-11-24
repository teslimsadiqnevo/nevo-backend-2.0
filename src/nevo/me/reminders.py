"""Remind a /me learner before their paid month runs out.

/me Phase 4's open end. There is no auto-renewal and no stored card, so a
month lapses unless the learner buys again; this is the reminder before it
does. It sends email and nothing else - it holds no payment service and can
charge nobody.

Who is reminded: a paid month ending within REMINDER_LEAD that is the last
month the learner holds (a renewal bought early, queued behind it, means
there is nothing to remind about), not reminded before, for a learner with
a verified address. reminder_sent_at is set only once the email is sent, so
a mail outage means tomorrow's run tries again rather than nobody being
told.

Runs only while ME_BILLING_ENABLED is on: with checkout closed there is
nothing a reminder could ask the learner to do.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from nevo.core.config import get_settings
from nevo.db.models.account import User
from nevo.db.models.me import MePurchase
from nevo.me.usage import LAGOS
from nevo.notifications import me_copy
from nevo.notifications.branding import render_email
from nevo.notifications.email import EmailDeliveryUnavailableError, ResendEmailDelivery

logger = logging.getLogger(__name__)

#: How long before the month ends the reminder goes. A chosen default,
#: awaiting Lydia.
REMINDER_LEAD = timedelta(days=3)


def ends_on(moment: datetime) -> str:
    """The end date as a learner in Lagos would say it: 27 November 2026."""

    local = moment.astimezone(LAGOS)
    return f"{local.day} {local:%B %Y}"


async def send_renewal_reminders(
    sessions: async_sessionmaker[AsyncSession],
    delivery: object,
    *,
    now: datetime | None = None,
) -> str:
    if not get_settings().me_billing_enabled:
        return "skipped: ME_BILLING_ENABLED is off"
    if not isinstance(delivery, ResendEmailDelivery):
        return "skipped: no email delivery"
    now = now or datetime.now(UTC)
    later = aliased(MePurchase)
    async with sessions() as session:
        due = (
            await session.execute(
                select(MePurchase, User)
                .join(User, User.id == MePurchase.learner_id)
                .where(
                    MePurchase.status == "success",
                    MePurchase.reminder_sent_at.is_(None),
                    MePurchase.period_end > now,
                    MePurchase.period_end <= now + REMINDER_LEAD,
                    User.email.is_not(None),
                    User.email_confirmed_at.is_not(None),
                    # The last month they hold: nothing paid runs past it.
                    select(func.count())
                    .where(
                        later.learner_id == MePurchase.learner_id,
                        later.status == "success",
                        later.period_end > MePurchase.period_end,
                    )
                    .scalar_subquery()
                    == 0,
                )
            )
        ).all()
        sent = failed = 0
        for purchase, learner in due:
            paragraphs = me_copy.renewal_paragraphs(
                first_name=learner.first_name, ends_on=ends_on(purchase.period_end)
            )
            try:
                await delivery.send(
                    to=str(learner.email),
                    subject=me_copy.RENEWAL_SUBJECT,
                    text=me_copy.renewal_text(
                        first_name=learner.first_name, ends_on=ends_on(purchase.period_end)
                    ),
                    html=render_email(heading=me_copy.RENEWAL_SUBJECT, paragraphs=paragraphs),
                )
            except EmailDeliveryUnavailableError:
                failed += 1
                continue
            except Exception:
                logger.warning("Renewal reminder for %s failed", purchase.id, exc_info=True)
                failed += 1
                continue
            purchase.reminder_sent_at = now
            await session.commit()
            sent += 1
    return f"sent {sent}, failed {failed}, due {len(due)}"
