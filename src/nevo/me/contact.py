"""The /me waitlist and enquiry: record, then tell the team.

Neither creates an account and neither touches the tier model. The record is
committed before anyone is emailed, so a mail outage costs an alert, never a
request. Alerts go to LEAD_ALERT_RECIPIENTS, the same people who receive
school leads.

The waitlist no longer catches under-18s: they are registered (ruling A).
The enquiry is where a learner wanting more than twenty-five lessons lands,
and where a lesson teacher, tutorial centre or school does - routed to
contact, not to a fourth price.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.db.models.me import MeContactRequest
from nevo.notifications.email import ResendEmailDelivery
from nevo.partner_inquiries.notifier import LeadAlertSettings

logger = logging.getLogger(__name__)

#: One request per address per kind in this window; repeats are accepted and
#: dropped, so the form cannot be used to flood the team's inbox.
REPEAT_WINDOW = timedelta(minutes=10)


async def record(
    session: AsyncSession,
    *,
    kind: str,
    email: str,
    name: str | None = None,
    who: str | None = None,
    note: str | None = None,
    learner_id=None,
    now: datetime | None = None,
) -> MeContactRequest | None:
    """Store a request; None if the same address just sent the same kind."""

    now = now or datetime.now(UTC)
    normal = email.strip().casefold()
    recent = await session.scalar(
        select(MeContactRequest.id).where(
            MeContactRequest.kind == kind,
            MeContactRequest.email == normal,
            MeContactRequest.created_at >= now - REPEAT_WINDOW,
        )
    )
    if recent is not None:
        return None
    request = MeContactRequest(
        kind=kind,
        email=normal,
        name=name,
        who=who,
        note=note,
        learner_id=learner_id,
        created_at=now,
    )
    session.add(request)
    await session.commit()
    return request


async def alert_team(delivery: object, request: MeContactRequest) -> None:
    """Best effort. Internal mail to the team, not words a learner reads."""

    if not isinstance(delivery, ResendEmailDelivery):
        return
    addresses = LeadAlertSettings().addresses
    if not addresses:
        return
    label = "waitlist sign-up" if request.kind == "waitlist" else "enquiry"
    lines = [
        f"New /me {label}",
        f"Email: {request.email}",
        f"Name: {request.name or '-'}",
        f"Who: {request.who or '-'}",
        f"Note: {request.note or '-'}",
        f"Signed-in learner: {'yes' if request.learner_id else 'no'}",
    ]
    for address in addresses:
        try:
            await delivery.send(
                to=address,
                subject=f"New /me {label}: {request.email}",
                text="\n".join(lines),
                html="<br>".join(escape(line) for line in lines),
            )
        except Exception:
            logger.warning("/me %s alert to %s failed", request.kind, address, exc_info=True)
