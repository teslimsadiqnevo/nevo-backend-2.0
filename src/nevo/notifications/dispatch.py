"""Raise a notification, once, from wherever the thing happened.

NotificationType declares nine kinds and only two were ever written: an admin
welcome and a PIN reset request. The other seven - an invoice issued, a roster
sync finishing or needing a look, SSO losing its connection, a consent action
waiting - were named, given categories and preference switches, and never
produced by anything. A teacher could mute them and a teacher could wait for
them; neither did anything, because they did not exist.

Every notification written here is also emailed: the delivery worker picks up
anything with a recipient who has an email address and has not muted its
category, so raising one is all a caller has to do.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nevo.db.models.frontend_support import Notification
from nevo.domain.accounts.vocabulary import NotificationType, UserRole

logger = logging.getLogger(__name__)


async def notify(
    session: AsyncSession,
    *,
    recipient_id: UUID,
    recipient_role: UserRole | str,
    notification_type: NotificationType,
    title: str,
    description: str,
    navigates_to: str | None = None,
) -> Notification:
    """Write one notification. The category follows the type on insert.

    Not committed here: the caller is inside a transaction that is doing the
    thing being announced, and an invoice that exists without its notification
    is better than a notification for an invoice that was rolled back.
    """

    record = Notification(
        recipient_id=recipient_id,
        recipient_role=(
            recipient_role.value if isinstance(recipient_role, UserRole) else recipient_role
        ),
        type=notification_type.value,
        title=title,
        description=description,
        navigates_to=navigates_to,
    )
    session.add(record)
    return record


async def notify_each(
    session: AsyncSession,
    *,
    recipients: list[tuple[UUID, UserRole | str]],
    notification_type: NotificationType,
    title: str,
    description: str,
    navigates_to: str | None = None,
) -> int:
    """The same notification to several people, usually a school's admins."""

    for recipient_id, role in recipients:
        await notify(
            session,
            recipient_id=recipient_id,
            recipient_role=role,
            notification_type=notification_type,
            title=title,
            description=description,
            navigates_to=navigates_to,
        )
    return len(recipients)
