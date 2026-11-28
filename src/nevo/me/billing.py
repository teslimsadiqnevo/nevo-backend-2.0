"""/me billing: a learner buys a month through Paystack hosted checkout.

/me Phase 4. School billing is untouched (invoice, bank transfer, the webhook
confirming receipt). This is the second band.

The rules, each of which exists because something went wrong:

* Off behind ME_BILLING_ENABLED, its own flag. A Paystack key being set never
  starts a checkout.
* Nothing about the instrument is stored - no card, no authorization code, no
  customer code - and nothing is ever charged with nobody present. No
  auto-renewal: a month lapses and the learner buys again.
* The verified webhook grants the month, re-checked against Paystack's API,
  never the redirect back to the app.
* Never grant for an amount or currency that was not asked for.

A month is one calendar month from payment. Buying the same tier again while
it is still active queues the new month after the current one; buying the
higher tier starts it at once. The learner holds the highest tier active now.
"""

from __future__ import annotations

import logging
import secrets
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from html import escape
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import User
from nevo.db.models.me import MePurchase
from nevo.domain.billing.vocabulary import PaymentTransactionStatus, PricingCurrency
from nevo.me import tiers
from nevo.me.references import REFERENCE_PREFIX
from nevo.me.tiers import Tier
from nevo.payments.entities import PaymentOutcome, ProviderTransaction
from nevo.payments.errors import PaymentNotFoundError
from nevo.payments.paystack import PaystackClient, to_minor_units

logger = logging.getLogger(__name__)

#: Card, bank, USSD and transfer: restricting to card would exclude the
#: students who do not have a working one.
CHANNELS = ["card", "bank", "ussd", "bank_transfer"]


class CheckoutRefused(Exception):
    def __init__(self, code: str, status_code: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class Checkout:
    authorization_url: str
    reference: str


@dataclass(frozen=True)
class Subscription:
    tier: Tier
    period_end: datetime | None
    reminder_sent_at: datetime | None


def add_one_month(moment: datetime) -> datetime:
    """The same day next month, clamped to that month's last day."""

    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    day = min(moment.day, monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


async def active_purchases(session: AsyncSession, learner_id, now: datetime) -> list[MePurchase]:
    return list(
        await session.scalars(
            select(MePurchase).where(
                MePurchase.learner_id == learner_id,
                MePurchase.status == "success",
                MePurchase.period_start <= now,
                MePurchase.period_end > now,
            )
        )
    )


async def current_purchase(session: AsyncSession, learner_id, now: datetime) -> MePurchase | None:
    """The paid month in force now: the highest tier among those active."""

    active = await active_purchases(session, learner_id, now)
    if not active:
        return None
    return max(
        active,
        key=lambda item: (tiers.by_key(item.tier_key) or tiers.FREE).lessons_per_month,
    )


async def subscription_for(
    session: AsyncSession, learner_id, now: datetime | None = None
) -> Subscription:
    now = now or datetime.now(UTC)
    best = await current_purchase(session, learner_id, now)
    if best is None:
        return Subscription(tier=tiers.FREE, period_end=None, reminder_sent_at=None)
    # When the learner's paid access actually ends: the last month queued
    # behind this one of the same tier, if they renewed early.
    queued_end = await session.scalar(
        select(MePurchase.period_end)
        .where(
            MePurchase.learner_id == learner_id,
            MePurchase.status == "success",
            MePurchase.tier_key == best.tier_key,
        )
        .order_by(MePurchase.period_end.desc())
        .limit(1)
    )
    return Subscription(
        tier=tiers.by_key(best.tier_key) or tiers.FREE,
        period_end=queued_end or best.period_end,
        reminder_sent_at=best.reminder_sent_at,
    )


async def start_checkout(
    session: AsyncSession,
    client: PaystackClient,
    learner: User,
    tier: Tier,
    *,
    callback_url: str,
    replaces: MePurchase | None = None,
    now: datetime | None = None,
) -> Checkout:
    """Record a pending purchase, then open Paystack's hosted checkout for it.

    The row is committed before Paystack is called, so a webhook that beats
    the response back still finds what it is for.
    """

    now = now or datetime.now(UTC)
    if tier.price_naira is None:
        raise CheckoutRefused("tier_not_for_sale", 422)
    if not learner.email or learner.email_confirmed_at is None:
        raise CheckoutRefused("email_unverified", 403)
    reference = f"{REFERENCE_PREFIX}{now:%Y%m%d}-{secrets.token_hex(8)}"
    amount = Decimal(tier.price_naira)
    purchase = MePurchase(
        learner_id=learner.id,
        tier_key=tier.key,
        amount_minor=to_minor_units(amount),
        currency=PricingCurrency.NGN.value,
        reference=reference,
        status="pending",
        created_at=now,
        replaces_reference=replaces.reference if replaces else None,
    )
    session.add(purchase)
    await session.commit()
    try:
        url = await client.initialize_transaction(
            email=learner.email,
            amount=amount,
            reference=reference,
            currency=PricingCurrency.NGN,
            metadata={"purpose": "me_month", "tier": tier.key},
            callback_url=callback_url,
            channels=CHANNELS,
        )
    except Exception as error:
        purchase.status = "failed"
        purchase.failure_reason = str(error)[:1000]
        await session.commit()
        raise
    purchase.checkout_url = url
    await session.commit()
    return Checkout(authorization_url=url, reference=reference)


LearnerStatus = Literal["pending", "abandoned", "success", "failed"]


def learner_status(purchase: MePurchase) -> LearnerStatus:
    """The states the checkout screen tells apart (Lydia, 26 and 28 November).

    pending: the money may have left the learner's bank and Paystack has not
    confirmed it. abandoned: the learner left Paystack's page without paying;
    the page is still live and payable, so this is not failed - calling it
    failed is what made learners pay twice. failed: genuinely did not go
    through, a wrong amount or Paystack's fraud check. None is final here: if
    Paystack later confirms the payment, the month is still granted.
    """

    if purchase.status in {"success", "pending", "abandoned"}:
        return purchase.status  # type: ignore[return-value]
    return "failed"


async def newest_unfinished(session: AsyncSession, learner_id) -> MePurchase | None:
    """The learner's latest checkout neither paid nor genuinely failed."""

    return await session.scalar(
        select(MePurchase)
        .where(
            MePurchase.learner_id == learner_id,
            MePurchase.status.in_(("pending", "abandoned")),
        )
        .order_by(MePurchase.created_at.desc())
        .limit(1)
    )


async def unseen_double_payment(session: AsyncSession, learner_id) -> MePurchase | None:
    """The latest double payment the learner has not been shown yet."""

    return await session.scalar(
        select(MePurchase)
        .where(
            MePurchase.learner_id == learner_id,
            MePurchase.double_paid_at.is_not(None),
            MePurchase.double_paid_seen_at.is_(None),
        )
        .order_by(MePurchase.double_paid_at.desc())
        .limit(1)
    )


async def paired_with(session: AsyncSession, purchase: MePurchase) -> MePurchase | None:
    """The other checkout of a pair started for one intention, if it was paid."""

    conditions = [MePurchase.replaces_reference == purchase.reference]
    if purchase.replaces_reference:
        conditions.append(MePurchase.reference == purchase.replaces_reference)
    return await session.scalar(
        select(MePurchase)
        .where(
            MePurchase.learner_id == purchase.learner_id,
            MePurchase.id != purchase.id,
            MePurchase.status == "success",
            or_(*conditions),
        )
        .order_by(MePurchase.paid_at.desc())
        .limit(1)
    )


async def still_waiting(
    session: AsyncSession, learner_id, now: datetime | None = None
) -> list[MePurchase]:
    """The learner's checkouts not yet settled either way, newest first.

    No time limit (Lydia, 26 November): a learner leaves the waiting state on
    Paystack's answer, never on our clock. Each one is put to Paystack again
    before it is shown, so a checkout Paystack calls abandoned drops out.
    """

    del now
    return list(
        await session.scalars(
            select(MePurchase)
            .where(
                MePurchase.learner_id == learner_id,
                MePurchase.status == "pending",
            )
            .order_by(MePurchase.created_at.desc())
            .limit(3)
        )
    )


class IndividualSettler:
    """Applies a verified Paystack transaction to a /me purchase.

    Called by PaymentService.handle_webhook for references this band made,
    after the signature is checked, the event de-duplicated and the
    transaction re-fetched from Paystack's API.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def __call__(self, transaction: ProviderTransaction) -> PaymentOutcome:
        async with self._sessions.begin() as session:
            purchase = await session.scalar(
                select(MePurchase)
                .where(MePurchase.reference == transaction.reference)
                .with_for_update()
            )
            if purchase is None:
                raise PaymentNotFoundError
            if purchase.status == "success":
                return _outcome(purchase, "This month was already granted.")

            status = transaction.status
            if status is PaymentTransactionStatus.SUCCESS and not _amount_matches(
                purchase, transaction
            ):
                purchase.status = "failed"
                purchase.failure_reason = (
                    f"Provider amount did not match: expected {purchase.amount_minor} "
                    f"{purchase.currency}, got {transaction.amount_minor} {transaction.currency}"
                )
                return _outcome(purchase, "The payment did not match what was asked for.")

            if status is PaymentTransactionStatus.SUCCESS:
                now = transaction.paid_at or datetime.now(UTC)
                queued_behind = await session.scalar(
                    select(MePurchase.period_end)
                    .where(
                        MePurchase.learner_id == purchase.learner_id,
                        MePurchase.status == "success",
                        MePurchase.tier_key == purchase.tier_key,
                        MePurchase.period_end > now,
                    )
                    .order_by(MePurchase.period_end.desc())
                    .limit(1)
                )
                start = queued_behind or now
                purchase.status = "success"
                purchase.paid_at = now
                purchase.provider_reference = transaction.provider_reference
                purchase.period_start = start
                purchase.period_end = add_one_month(start)
                purchase.failure_reason = None
                # transaction.authorization is deliberately never read.
                # Paid twice for one intention (Lydia, 28 November): both
                # months are kept, no refund goes out by itself. The learner
                # is told, and the team is emailed (alert_double_payments).
                if await paired_with(session, purchase) is not None:
                    purchase.double_paid_at = now
                    return _outcome(purchase, "Month granted; the learner paid twice.")
                return _outcome(purchase, "Month granted.")

            if status is PaymentTransactionStatus.PENDING:
                # An abandoned checkout the learner reopened and paid by
                # transfer is waiting again, not abandoned.
                if purchase.status == "abandoned":
                    purchase.status = "pending"
                return _outcome(purchase, "Payment still pending.")
            purchase.status = (
                "abandoned" if status is PaymentTransactionStatus.ABANDONED else "failed"
            )
            purchase.failure_reason = (transaction.gateway_message or "")[:1000] or None
            return _outcome(purchase, "The payment was not completed.")


def _amount_matches(purchase: MePurchase, transaction: ProviderTransaction) -> bool:
    if transaction.amount_minor != purchase.amount_minor:
        return False
    currency = transaction.currency.strip().upper()
    return not currency or currency == purchase.currency.upper()


def _outcome(purchase: MePurchase, message: str) -> PaymentOutcome:
    status = {
        "success": PaymentTransactionStatus.SUCCESS,
        "failed": PaymentTransactionStatus.FAILED,
        "abandoned": PaymentTransactionStatus.ABANDONED,
    }.get(purchase.status, PaymentTransactionStatus.PENDING)
    return PaymentOutcome(
        transaction_id=purchase.id,
        invoice_id=None,
        reference=purchase.reference,
        status=status,
        invoice_paid=False,
        payment_method_saved=False,
        message=message,
    )


async def alert_double_payments(
    sessions: async_sessionmaker[AsyncSession], delivery: object
) -> str:
    """Email the team about each double payment once (Lydia, 28 November).

    The log she asked to be able to see: an automatic refund is a bigger
    liability than this narrow case, and these emails are what show whether
    that stays true. The marker is set only after the emails go, so a mail
    outage means the next run tries again.
    """

    from nevo.notifications.email import ResendEmailDelivery
    from nevo.partner_inquiries.notifier import LeadAlertSettings

    if not isinstance(delivery, ResendEmailDelivery):
        return "skipped: no email delivery"
    addresses = LeadAlertSettings().addresses
    if not addresses:
        return "skipped: no LEAD_ALERT_RECIPIENTS"
    alerted = 0
    async with sessions() as session:
        rows = (
            await session.execute(
                select(MePurchase, User)
                .join(User, User.id == MePurchase.learner_id)
                .where(
                    MePurchase.double_paid_at.is_not(None),
                    MePurchase.double_paid_alerted_at.is_(None),
                )
            )
        ).all()
        for purchase, learner in rows:
            other = await paired_with(session, purchase)
            lines = [
                "A /me learner paid twice for one month. Both months were granted; "
                "nothing was refunded.",
                f"Learner: {learner.email or learner.id}",
                f"Second payment: {purchase.reference} ({purchase.tier_key}, "
                f"{purchase.amount_minor / 100:,.0f} {purchase.currency})",
                f"First payment: {other.reference if other else '-'}",
                f"Paid access now ends: {purchase.period_end:%d %B %Y}",
            ]
            sent = 0
            for address in addresses:
                try:
                    await delivery.send(
                        to=address,
                        subject=f"/me double payment: {purchase.reference}",
                        text="\n".join(lines),
                        html="<br>".join(escape(line) for line in lines),
                    )
                    sent += 1
                except Exception:
                    logger.warning("/me double-payment alert to %s failed", address, exc_info=True)
            if sent:
                purchase.double_paid_alerted_at = datetime.now(UTC)
                await session.commit()
                alerted += 1
    return f"double payments alerted {alerted} of {len(rows)}"
