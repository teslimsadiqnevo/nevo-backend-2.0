import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import User
from nevo.db.models.consent import ConsentInvitation, ConsentNotificationOutbox
from nevo.domain.consent.vocabulary import (
    ConsentDeliveryStatus,
    ConsentNotificationKind,
    ParentContactMethod,
)
from nevo.notifications.branding import render_email
from nevo.notifications.email import ResendEmailDelivery

MAX_ATTEMPTS = 6
EMAIL_SUBJECT = "Review your child's Nevo consent request"
RECEIPT_SUBJECT = "Your Nevo consent - a copy for your records"


def opening_line(child_name: str | None) -> str:
    """What the parent reads first. Copy from the CEO, 29 September.

    It replaces "Nevo needs your confirmation before your child's learning
    data is used", which asked for something without saying what turned on it.
    This says what the parent's answer actually decides, and it is true: a
    child whose consent is outstanding is refused at the door with
    consent_pending, so nothing does start before then.
    """

    if child_name:
        return (
            f"{child_name}'s learning begins as soon as you give permission. "
            "Nothing starts before then."
        )
    # No first name on the roster. The same promise, without pretending to a
    # name we do not have.
    return (
        "Your child's learning begins as soon as you give permission. Nothing starts before then."
    )


def consent_message(consent_url: str, child_name: str | None = None) -> str:
    return (
        f"{opening_line(child_name)} "
        f"Review and respond here: {consent_url}\n\n"
        "This link expires in 7 days. If you did not expect this, ignore this message."
    )


def consent_html(consent_url: str, child_name: str | None = None) -> str:
    """The same words as the plain-text version, in Nevo's shell.

    This is the message most likely to be mistaken for a phishing attempt: it
    arrives unexpectedly, mentions somebody's child, and asks them to click.
    Looking like Nevo is part of it being trustworthy.
    """

    return render_email(
        heading="A decision about your child's learning",
        # The preview line an inbox shows before the mail is opened. It
        # carried the same sentence the new copy replaced, so leaving it would
        # have put the struck wording back in front of every parent, in the
        # one line they read first.
        preheader="Nothing starts until you give permission. The link expires in 7 days.",
        paragraphs=[opening_line(child_name)],
        cta=("Review and respond", consent_url),
        footnote=(
            "This link expires in 7 days. If you did not expect this, you can "
            "ignore this message, and nothing about your child changes."
        ),
    )


def receipt_html() -> str:
    """Carries no link, for the same reason the text version does not."""

    return render_email(
        heading="Your consent has been recorded",
        preheader="This message is your copy.",
        paragraphs=[
            "You gave consent for your child to use Nevo. This message is your copy.",
            "You can withdraw that consent at any time, or ask what data we "
            "hold, from the link your school sent you.",
        ],
        footnote="If this was not you, contact your school straight away.",
    )


def receipt_message() -> str:
    """The copy the consent page promises the parent.

    Deliberately carries no link. This is a record of a decision already
    made, and a fresh link in it would be one more thing that can be
    forwarded or phished.
    """
    return (
        "You gave consent for your child to use Nevo. This message is your copy.\n\n"
        "You can withdraw that consent at any time, or ask what data we hold, "
        "from the link your school sent you.\n\n"
        "If this was not you, contact your school straight away."
    )


class ConsentDeliveryWorker:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        email: ResendEmailDelivery,
        poll_seconds: float = 5,
    ) -> None:
        self._sessions = sessions
        self._email = email
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
        outbox_id, _method, destination, consent_url, kind, child_name = claimed
        is_receipt = kind is ConsentNotificationKind.RECEIPT
        message = receipt_message() if is_receipt else consent_message(consent_url, child_name)
        try:
            await self._email.send(
                to=destination,
                subject=RECEIPT_SUBJECT if is_receipt else EMAIL_SUBJECT,
                text=message,
                html=(receipt_html() if is_receipt else consent_html(consent_url, child_name)),
            )
        except Exception as error:
            await self._failed(outbox_id, error)
        else:
            await self._sent(outbox_id)
        return True

    async def _run(self) -> None:
        while True:
            if not await self.process_next():
                await asyncio.sleep(self._poll_seconds)

    async def _claim(
        self,
    ) -> tuple[UUID, ParentContactMethod, str, str, ConsentNotificationKind, str | None] | None:
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
                    # A request is blanked once used so the link is not sent
                    # again; a receipt never carries one in the first place.
                    or_(
                        ConsentNotificationOutbox.kind == ConsentNotificationKind.RECEIPT,
                        ConsentNotificationOutbox.consent_url != "",
                    ),
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
            # The child's own name, so the email can say whose learning is
            # waiting. One join, inside the claim that is already open.
            child_name = await session.scalar(
                select(User.first_name)
                .join(ConsentInvitation, ConsentInvitation.student_id == User.id)
                .where(ConsentInvitation.id == record.invitation_id)
            )
            return (
                record.id,
                record.contact_method,
                record.destination,
                record.consent_url,
                record.kind,
                child_name,
            )

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
