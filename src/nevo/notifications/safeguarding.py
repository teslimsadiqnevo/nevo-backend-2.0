"""Tell a school's Learning Support holders when something new is flagged.

S11/S16, 25 November 2026. The safeguarding list (GET /safety/events) worked,
but nothing told a holder a new entry had arrived: they saw it only if they
happened to open the list. Now each new entry that the list would show raises
a `safeguarding_flag` notification for every active holder in the school,
and the notification email worker sends it on like any other.

Exactly the list's own rule, so the alert and the list never disagree: a
block or safeguard, about a student of this school, that is not a bare name
finding on its own. No child is named in it; the list is where that is read.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.db.models.account import User
from nevo.db.models.permission import LearningSupportGrant
from nevo.domain.accounts.vocabulary import NotificationType, UserStatus
from nevo.notifications.dispatch import notify

logger = logging.getLogger(__name__)

#: Shared with safety_retention.actionable_by_an_adult: a privacy finding on
#: its own is a name in a question, not something an adult acts on.
NOT_ACTIONABLE_ALONE = "privacy_abuse"

#: Staff-facing words, pending Lydia. Neutral, and naming no child.
TITLE = "Something new on the safeguarding list"
DESCRIPTION = "A new entry is waiting on your school's safeguarding list."
#: Where the app shows the list. Unknown until Yinka confirms the path.
NAVIGATES_TO: str | None = None


def appears_on_the_list(event) -> bool:
    if event.action not in {"block", "safeguard"}:
        return False
    if event.school_id is None or event.student_id is None:
        return False
    return list(event.categories or ()) != [NOT_ACTIONABLE_ALONE]


async def notify_learning_support(session: AsyncSession, event) -> int:
    """Raise the notification for each active holder. Returns how many."""

    if not appears_on_the_list(event):
        return 0
    student = await session.get(User, event.student_id)
    if student is None or student.school_id != event.school_id or student.role.value != "student":
        return 0
    holders = (
        await session.execute(
            select(User.id, User.role)
            .join(LearningSupportGrant, LearningSupportGrant.holder_user_id == User.id)
            .where(
                LearningSupportGrant.school_id == event.school_id,
                LearningSupportGrant.revoked_at.is_(None),
                User.school_id == event.school_id,
                User.status == UserStatus.ACTIVE,
            )
            .distinct()
        )
    ).all()
    for holder_id, role in holders:
        await notify(
            session,
            recipient_id=holder_id,
            recipient_role=role,
            notification_type=NotificationType.SAFEGUARDING_FLAG,
            title=TITLE,
            description=DESCRIPTION,
            navigates_to=NAVIGATES_TO,
        )
    return len(holders)
