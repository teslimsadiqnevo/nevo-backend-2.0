"""Requeue the email that gave up while no provider was configured.

The Resend and Paystack settings did not come across in the move to Heroku,
so for days every send raised "not configured". Both queues retry with
backoff and then stop at six attempts - the notification queue marks a row
``permanently_failed``, and the consent outbox leaves it ``failed`` with its
attempts spent. Neither will retry on its own, so setting the keys fixes new
mail and does nothing for the invitations and notifications already given up
on. This requeues those.

Run it **after** the keys are set. Nothing it requeues can be sent before
then, and sending is what proves the keys work.

Two things it will not do.

It will not requeue a row that failed for its own reason. A row whose last
error is a refused address or a rejected payload failed because of the
address or the payload, and resetting it just spends six more attempts
reaching the same conclusion - and, for a parent, risks a second copy of an
invitation they already received. Only rows whose last error says the
provider was unavailable are touched, unless --every-failure is passed,
which is there for the case where the error text turns out not to match and
a human has looked at the list first.

It will not send anything itself. It resets the attempt counters and hands
the rows back to the workers that own them, which already know how to send,
how to back off, and how to record what happened. A script that sent mail
directly would be a second delivery path with its own bugs, and the thing
it would be sending is a consent request about somebody's child.

Dry run by default. Nothing is written without --apply.

T3, 20 November.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import func, select

from nevo.core.config import get_settings
from nevo.db.models.consent import ConsentNotificationOutbox
from nevo.db.models.frontend_support import NotificationEmailDelivery
from nevo.db.session import create_engine, create_session_factory
from nevo.domain.consent.vocabulary import ConsentDeliveryStatus

#: The six-attempt ceiling both workers stop at. Imported rather than
#: repeated, so raising one of them cannot leave this script disagreeing
#: with the worker about what "gave up" means.
from nevo.consent.worker import MAX_ATTEMPTS as CONSENT_MAX_ATTEMPTS
from nevo.notifications.worker import MAX_ATTEMPTS as NOTIFICATION_MAX_ATTEMPTS

#: What a send raises when there is no provider. EmailDeliveryUnavailableError
#: carries this text, and both workers record ``str(error)`` as last_error.
UNAVAILABLE_MARKERS = (
    "not configured",
    "EmailDeliveryUnavailable",
    "unavailable",
)


def _blames_the_provider(last_error: str | None) -> bool:
    """Whether this row failed because we had no way to send, not because of
    anything about the message or its recipient."""
    if not last_error:
        # No reason recorded. Treated as ours: a row that never got far
        # enough to record an error never reached the provider either.
        return True
    folded = last_error.casefold()
    return any(marker.casefold() in folded for marker in UNAVAILABLE_MARKERS)


async def main(*, apply: bool, every_failure: bool, limit: int | None) -> None:
    engine = create_engine(get_settings().database_url)
    counts: Counter[str] = Counter()
    now = datetime.now(UTC)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            # ---- Notification email: given up at the ceiling.
            notifications = list(
                await session.scalars(
                    select(NotificationEmailDelivery).where(
                        NotificationEmailDelivery.delivered_at.is_(None),
                        NotificationEmailDelivery.attempt_count
                        >= NOTIFICATION_MAX_ATTEMPTS,
                    )
                )
            )
            # ---- Consent invitations: failed with their attempts spent.
            consent = list(
                await session.scalars(
                    select(ConsentNotificationOutbox).where(
                        ConsentNotificationOutbox.sent_at.is_(None),
                        ConsentNotificationOutbox.attempt_count >= CONSENT_MAX_ATTEMPTS,
                    )
                )
            )

        print(f"Found {len(notifications)} notification email(s) and "
              f"{len(consent)} consent notification(s) that gave up.\n")

        chosen_notifications = []
        for row in notifications:
            ours = _blames_the_provider(row.last_error)
            counts["notification_provider" if ours else "notification_its_own_fault"] += 1
            if ours or every_failure:
                chosen_notifications.append(row)

        chosen_consent = []
        for row in consent:
            ours = _blames_the_provider(row.last_error)
            counts["consent_provider" if ours else "consent_its_own_fault"] += 1
            if ours or every_failure:
                chosen_consent.append(row)

        if limit is not None:
            chosen_notifications = chosen_notifications[:limit]
            chosen_consent = chosen_consent[:limit]

        # Say why the ones being left alone are being left alone, grouped, so
        # a human can see whether the error text matched what we expected.
        skipped = Counter()
        for row in notifications + consent:
            if not _blames_the_provider(row.last_error):
                skipped[(row.last_error or "")[:90]] += 1
        if skipped:
            print("Left alone - these failed for their own reason:")
            for reason, count in skipped.most_common():
                print(f"  {count:4d}  {reason}")
            print()

        print(f"Would requeue {len(chosen_notifications)} notification email(s) "
              f"and {len(chosen_consent)} consent notification(s).")

        if not apply:
            print("\nDry run. Nothing written. Re-run with --apply.")
            return

        async with factory.begin() as session:
            for row in chosen_notifications:
                record = await session.get(NotificationEmailDelivery, row.id)
                if record is None or record.delivered_at is not None:
                    continue
                # "failed", not "pending", and this matters. The worker
                # claims a delivery whose status is "failed" or "processing",
                # or whose row does not exist at all; "pending" is only the
                # default a brand-new row is created with, so once a row
                # exists, "pending" is never claimed by anything. Setting it
                # here made these rows invisible rather than queued - worse
                # than permanently_failed, which at least described reality.
                record.status = "failed"
                record.attempt_count = 0
                record.next_attempt_at = now
                record.last_error = None
                counts["notification_requeued"] += 1
            for row in chosen_consent:
                record = await session.get(ConsentNotificationOutbox, row.id)
                if record is None or record.sent_at is not None:
                    continue
                record.status = ConsentDeliveryStatus.QUEUED
                record.attempt_count = 0
                record.next_attempt_at = now
                record.last_error = None
                counts["consent_requeued"] += 1

        print("\nRequeued. The workers own the sending from here.")
        for key, value in sorted(counts.items()):
            print(f"  {key}: {value}")

        # The queues are drained by the background workers, which poll every
        # twenty seconds. Nothing else to run.
        async with factory() as session:
            still_waiting = await session.scalar(
                select(func.count())
                .select_from(NotificationEmailDelivery)
                .where(
                    NotificationEmailDelivery.delivered_at.is_(None),
                    NotificationEmailDelivery.status == "failed",
                    NotificationEmailDelivery.attempt_count == 0,
                )
            )
            print(f"  notification queue now waiting to send: {still_waiting}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="write the changes (default: dry run)"
    )
    parser.add_argument(
        "--every-failure",
        action="store_true",
        help=(
            "requeue rows that failed for their own reason too. Only after "
            "reading the dry run's list of them."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="requeue at most this many of each, to try a few first",
    )
    args = parser.parse_args()
    asyncio.run(
        main(apply=args.apply, every_failure=args.every_failure, limit=args.limit)
    )
