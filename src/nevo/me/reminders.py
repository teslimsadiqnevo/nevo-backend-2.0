"""Tell a /me learner before their paid month runs out, and when it has.

Nothing renews on its own and no card is kept, so a month lapses unless the
learner buys again. Lydia's ruling F (24 November 2026): two reminders.
Seven days before, because three alone is too late, and one on the day it
lapses, because without it the lapse is silent. Email only: this holds no
payment service and can charge nobody.

Who is told: a paid month that is the last the learner holds (a month bought
early and queued behind it means there is nothing to tell), not told before,
for a learner with a verified address. Each marker is set only once its
email is sent, so a mail outage means the next run tries again.

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
from nevo.notifications.links import me_tiers_url

logger = logging.getLogger(__name__)

#: How long before the month ends the first reminder goes (ruling F).
REMINDER_LEAD = timedelta(days=7)
#: How far back a lapse still counts as "today" for the second. A little over
#: a day, so a daily run that starts late does not skip a learner.
LAPSE_WINDOW = timedelta(hours=30)


def ends_on(moment: datetime) -> str:
    """The end date as a learner in Lagos would say it: 27 November 2026."""

    local = moment.astimezone(LAGOS)
    return f"{local.day} {local:%B %Y}"


def _last_month_held():
    later = aliased(MePurchase)
    return (
        select(func.count())
        .where(
            later.learner_id == MePurchase.learner_id,
            later.status == "success",
            later.period_end > MePurchase.period_end,
        )
        .scalar_subquery()
        == 0
    )


async def _due(session: AsyncSession, *conditions):
    return (
        await session.execute(
            select(MePurchase, User)
            .join(User, User.id == MePurchase.learner_id)
            .where(
                MePurchase.status == "success",
                User.email.is_not(None),
                User.email_confirmed_at.is_not(None),
                _last_month_held(),
                *conditions,
            )
        )
    ).all()


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
    link = me_tiers_url(delivery.frontend_base_url)
    sent = {"ending": 0, "lapsed": 0}
    failed = 0

    async with sessions() as session:
        ending = await _due(
            session,
            MePurchase.reminder_sent_at.is_(None),
            MePurchase.period_end > now,
            MePurchase.period_end <= now + REMINDER_LEAD,
        )
        lapsed = await _due(
            session,
            MePurchase.lapse_notice_sent_at.is_(None),
            MePurchase.period_end <= now,
            MePurchase.period_end > now - LAPSE_WINDOW,
        )
        for kind, rows in (("ending", ending), ("lapsed", lapsed)):
            for purchase, learner in rows:
                if kind == "ending":
                    date = ends_on(purchase.period_end)
                    subject = me_copy.renewal_subject(ends_on=date)
                    paragraphs = me_copy.renewal_paragraphs(
                        first_name=learner.first_name, ends_on=date
                    )
                    footnote = me_copy.RENEWAL_FOOTNOTE
                else:
                    subject = me_copy.LAPSED_SUBJECT
                    paragraphs = me_copy.lapsed_paragraphs(first_name=learner.first_name)
                    footnote = None
                lines = [*paragraphs, f"{me_copy.RENEWAL_CTA}: {link}"]
                if footnote:
                    lines.append(footnote)
                text = "\n\n".join(lines)
                try:
                    await delivery.send(
                        to=str(learner.email),
                        subject=subject,
                        text=text + "\n",
                        html=render_email(
                            heading=subject,
                            paragraphs=paragraphs,
                            cta=(me_copy.RENEWAL_CTA, link),
                            footnote=footnote,
                        ),
                    )
                except EmailDeliveryUnavailableError:
                    failed += 1
                    continue
                except Exception:
                    logger.warning("/me %s notice for %s failed", kind, purchase.id, exc_info=True)
                    failed += 1
                    continue
                if kind == "ending":
                    purchase.reminder_sent_at = now
                else:
                    purchase.lapse_notice_sent_at = now
                await session.commit()
                sent[kind] += 1
    return f"seven-day {sent['ending']}, lapsed {sent['lapsed']}, failed {failed}"
