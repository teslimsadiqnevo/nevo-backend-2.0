import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import User
from nevo.db.models.frontend_support import Notification, NotificationEmailDelivery
from nevo.db.models.product import NotificationPreference
from nevo.notifications.email import ResendEmailDelivery

MAX_ATTEMPTS = 6


class NotificationEmailWorker:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        delivery: ResendEmailDelivery,
        poll_seconds: float = 5,
    ) -> None:
        self._sessions = sessions
        self._delivery = delivery
        self._poll_seconds = poll_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="notification-email-delivery")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def process_next(self) -> bool:
        claimed = await self._claim()
        if claimed is None:
            return False
        delivery_id, recipient, title, description = claimed
        try:
            await self._delivery.send(to=recipient, subject=title, text=description)
        except Exception as error:
            await self._mark_failed(delivery_id, error)
        else:
            await self._mark_delivered(delivery_id)
        return True

    async def _run(self) -> None:
        while True:
            worked = await self.process_next()
            if not worked:
                await asyncio.sleep(self._poll_seconds)

    async def _claim(self) -> tuple[UUID, str, str, str] | None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            row = (
                await session.execute(
                    select(Notification, User, NotificationEmailDelivery)
                    .join(User, User.id == Notification.recipient_id)
                    .outerjoin(
                        NotificationPreference,
                        and_(
                            NotificationPreference.user_id == User.id,
                            NotificationPreference.category == Notification.category,
                        ),
                    )
                    .outerjoin(
                        NotificationEmailDelivery,
                        NotificationEmailDelivery.notification_id == Notification.id,
                    )
                    .where(
                        User.email.is_not(None),
                        or_(
                            NotificationPreference.id.is_(None),
                            NotificationPreference.email.is_(True),
                        ),
                        or_(
                            NotificationEmailDelivery.id.is_(None),
                            and_(
                                NotificationEmailDelivery.status.in_(("failed", "processing")),
                                NotificationEmailDelivery.attempt_count < MAX_ATTEMPTS,
                                NotificationEmailDelivery.next_attempt_at <= now,
                            ),
                        ),
                    )
                    .order_by(Notification.created_at)
                    .with_for_update(of=Notification, skip_locked=True)
                    .limit(1)
                )
            ).first()
            if row is None:
                return None
            notification, user, delivery = row
            if delivery is None:
                delivery = NotificationEmailDelivery(notification_id=notification.id)
                session.add(delivery)
                await session.flush()
            delivery.status = "processing"
            delivery.attempt_count += 1
            delivery.next_attempt_at = now + timedelta(minutes=10)
            delivery.last_error = None
            return delivery.id, str(user.email), notification.title, notification.description

    async def _mark_delivered(self, delivery_id: UUID) -> None:
        async with self._sessions.begin() as session:
            record = await session.get(NotificationEmailDelivery, delivery_id)
            if record is not None:
                record.status = "delivered"
                record.delivered_at = datetime.now(UTC)

    async def _mark_failed(self, delivery_id: UUID, error: Exception) -> None:
        async with self._sessions.begin() as session:
            record = await session.get(NotificationEmailDelivery, delivery_id)
            if record is None:
                return
            record.status = (
                "failed" if record.attempt_count < MAX_ATTEMPTS else "permanently_failed"
            )
            record.next_attempt_at = datetime.now(UTC) + timedelta(
                minutes=min(60, 2 ** max(0, record.attempt_count - 1))
            )
            record.last_error = str(error)[:1000]
