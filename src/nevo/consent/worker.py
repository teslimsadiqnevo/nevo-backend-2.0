import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.consent.delivery import TermiiSmsDelivery
from nevo.db.models.consent import ConsentNotificationOutbox
from nevo.domain.consent.vocabulary import ConsentDeliveryStatus, ParentContactMethod
from nevo.notifications.email import ResendEmailDelivery

MAX_ATTEMPTS = 6
EMAIL_SUBJECT = "Review your child's Nevo consent request"


def consent_message(consent_url: str) -> str:
    return (
        "Nevo needs your confirmation before your child's learning data is used. "
        f"Review and respond here: {consent_url}\n\n"
        "This link expires in 7 days. If you did not expect this, ignore this message."
    )


class ConsentDeliveryWorker:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        email: ResendEmailDelivery,
        sms: TermiiSmsDelivery,
        poll_seconds: float = 5,
    ) -> None:
        self._sessions = sessions
        self._email = email
        self._sms = sms
        self._poll_seconds = poll_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="consent-delivery")

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
        outbox_id, method, destination, consent_url = claimed
        message = consent_message(consent_url)
        try:
            if method is ParentContactMethod.EMAIL:
                await self._email.send(
                    to=destination,
                    subject=EMAIL_SUBJECT,
                    text=message,
                )
            else:
                await self._sms.send(to=destination, text=message)
        except Exception as error:
            await self._failed(outbox_id, error)
        else:
            await self._sent(outbox_id)
        return True

    async def _run(self) -> None:
        while True:
            if not await self.process_next():
                await asyncio.sleep(self._poll_seconds)

    async def _claim(self) -> tuple[UUID, ParentContactMethod, str, str] | None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            record = await session.scalar(
                select(ConsentNotificationOutbox)
                .where(
                    ConsentNotificationOutbox.status.in_(
                        (ConsentDeliveryStatus.QUEUED, ConsentDeliveryStatus.FAILED)
                    ),
                    ConsentNotificationOutbox.attempt_count < MAX_ATTEMPTS,
                    ConsentNotificationOutbox.next_attempt_at <= now,
                    ConsentNotificationOutbox.consent_url != "",
                )
                .order_by(ConsentNotificationOutbox.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            record.status = ConsentDeliveryStatus.PROCESSING
            record.attempt_count += 1
            record.last_error = None
            return record.id, record.contact_method, record.destination, record.consent_url

    async def _sent(self, outbox_id: UUID) -> None:
        async with self._sessions.begin() as session:
            record = await session.get(ConsentNotificationOutbox, outbox_id)
            if record is not None:
                record.status = ConsentDeliveryStatus.SENT
                record.sent_at = datetime.now(UTC)

    async def _failed(self, outbox_id: UUID, error: Exception) -> None:
        async with self._sessions.begin() as session:
            record = await session.get(ConsentNotificationOutbox, outbox_id)
            if record is not None:
                record.status = ConsentDeliveryStatus.FAILED
                record.last_error = str(error)[:1000]
                record.next_attempt_at = datetime.now(UTC) + timedelta(
                    minutes=min(60, 2 ** max(0, record.attempt_count - 1))
                )
