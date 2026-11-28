"""/me Phase 4: tiers, checkout and the learner's subscription.

Checkout is closed (404, as if absent) unless ME_BILLING_ENABLED is set -
never opened by a Paystack key being present. The month is granted by the
verified webhook (POST /api/billing/payments/webhook, which already handles
school receipts), never by the learner arriving back from Paystack.

GET /me/checkout/{reference} lets the app say which of four states a
payment is in (Lydia, 26 and 28 November): a bank transfer or USSD payment
can sit pending at Paystack, and a learner told "we are taking payment"
while their money has already left the bank will pay twice. A checkout left
without paying is abandoned, not failed: Paystack's page is still payable,
and the app offers to finish it rather than start a second. It asks Paystack's API, the
same check the webhook makes, so it can grant the month a little sooner but
never on the learner's word.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, update

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.response_models import CamelResponse
from nevo.consent.guardian import upload_blocked_by_consent
from nevo.core.config import get_settings
from nevo.db.models.account import User
from nevo.db.models.me import MePurchase
from nevo.me import billing, tiers
from nevo.payments.errors import PaymentError
from nevo.payments.service import PaymentService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["me"])


class MeTierResponse(CamelResponse):
    key: str
    lessons_per_month: int
    #: Whole naira; omitted for the free tier.
    price_naira: int | None = None
    currency: Literal["NGN"] = "NGN"


class MeTiersResponse(CamelResponse):
    tiers: list[MeTierResponse]
    #: Whether checkout is open. False until ME_BILLING_ENABLED is set.
    purchasable: bool
    #: Above the top tier a learner is routed to contact, not to a price.
    above_top_tier: Literal["contact"] = "contact"


class MeCheckoutRequest(BaseModel):
    model_config = CAMEL_CONFIG

    tier: Literal["monthly_12", "monthly_25"]
    #: Start a new checkout even though an earlier one is unfinished. Without
    #: it, one waiting on the bank is refused with payment_pending, and one
    #: left on Paystack's page with payment_abandoned (carrying paymentUrl to
    #: finish it), so the learner is asked before they pay twice.
    pay_again: bool = False


class MeCheckoutResponse(CamelResponse):
    authorization_url: str
    reference: str


class MeCheckoutStatusResponse(CamelResponse):
    reference: str
    tier: str
    #: pending: waiting on the bank, do not pay again. abandoned: left on
    #: Paystack's page without paying; it can still be finished. success: the
    #: month is granted. failed: genuinely did not go through (a wrong amount,
    #: Paystack's fraud check).
    status: billing.LearnerStatus
    #: When the month bought by this payment ends. Only on success.
    period_end: datetime | None = None
    #: Paystack's page for this checkout, to finish it. Only when abandoned,
    #: and only for checkouts started from 28 November, when it began to be kept.
    payment_url: str | None = None
    #: On success: this and another checkout for the same month both went
    #: through, and the learner holds both months.
    paid_twice: bool | None = None


class MePendingPayment(CamelResponse):
    reference: str
    tier: str


class MeDoublePayment(CamelResponse):
    #: The first payment, then the second.
    references: list[str]
    tier: str
    #: When paid access ends now, both months included.
    period_end: datetime | None = None


class MeSubscriptionResponse(CamelResponse):
    tier: str
    #: When paid access ends, renewals already bought included. Omitted on
    #: the free tier. Nothing renews by itself.
    period_end: datetime | None = None
    renewal_reminder_sent_at: datetime | None = None
    auto_renews: Literal[False] = False
    #: A payment the learner made that Paystack has not confirmed yet, newest
    #: first. While it is present the app shows "Your payment is still being
    #: confirmed" in place of the upgrade prompt (Lydia, 26 November), and
    #: polls GET /me/checkout/{reference}. Omitted when nothing is waiting.
    pending_payment: MePendingPayment | None = None
    #: Two payments for one intention both went through (Lydia, 28 November).
    #: Shown until POST /me/subscription/double-payment/seen. Omitted otherwise.
    double_payment: MeDoublePayment | None = None


@router.get("/me/tiers", response_model=MeTiersResponse, response_model_exclude_none=True)
async def me_tiers(principal: PrincipalDependency) -> MeTiersResponse:
    del principal
    return MeTiersResponse(
        tiers=[
            MeTierResponse(
                key=tier.key,
                lessons_per_month=tier.lessons_per_month,
                price_naira=tier.price_naira,
            )
            for tier in tiers.TIERS
        ],
        purchasable=get_settings().me_billing_enabled,
    )


@router.post("/me/checkout", response_model=MeCheckoutResponse, status_code=status.HTTP_201_CREATED)
async def me_checkout(
    payload: MeCheckoutRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
    request: Request,
) -> MeCheckoutResponse:
    if not get_settings().me_billing_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
    service = getattr(request.app.state, "payment_service", None)
    if not isinstance(service, PaymentService) or not service.configured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "payment_provider_unavailable"}
        )
    learner = await session.get(User, principal.user_id)
    if learner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
    if await upload_blocked_by_consent(session, learner):
        # Nothing to buy lessons for until a guardian consents.
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "upload_consent_required"})
    if not payload.pay_again:
        for earlier in await billing.still_waiting(session, learner.id):
            if await _ask_paystack(service, session, earlier) and earlier.status == "pending":
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail={"code": "payment_pending", "reference": earlier.reference},
                )
        left = await billing.newest_unfinished(session, learner.id)
        if (
            left is not None
            and left.status == "abandoned"
            and left.checkout_url
            and await _ask_paystack(service, session, left)
            and left.status == "abandoned"
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "payment_abandoned",
                    "reference": left.reference,
                    "paymentUrl": left.checkout_url,
                },
            )
    replaces = await billing.newest_unfinished(session, learner.id)
    tier = tiers.by_key(payload.tier)
    assert tier is not None
    try:
        checkout = await billing.start_checkout(
            session,
            service.client,
            learner,
            tier,
            callback_url=str(service.settings.me_callback_url),
            replaces=replaces,
        )
    except billing.CheckoutRefused as refusal:
        raise HTTPException(refusal.status_code, detail={"code": refusal.code}) from refusal
    except PaymentError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail={"code": error.code}) from error
    return MeCheckoutResponse(
        authorization_url=checkout.authorization_url, reference=checkout.reference
    )


@router.get(
    "/me/checkout/{reference}",
    response_model=MeCheckoutStatusResponse,
    response_model_exclude_none=True,
)
async def me_checkout_status(
    reference: str,
    principal: PrincipalDependency,
    session: DatabaseSession,
    request: Request,
) -> MeCheckoutStatusResponse:
    """Which state one of the learner's own payments is in. Poll while pending."""

    if not get_settings().me_billing_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
    purchase = await session.scalar(
        select(MePurchase).where(
            MePurchase.reference == reference, MePurchase.learner_id == principal.user_id
        )
    )
    if purchase is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
    if purchase.status in {"pending", "abandoned"}:
        service = getattr(request.app.state, "payment_service", None)
        if isinstance(service, PaymentService) and service.configured:
            await _ask_paystack(service, session, purchase)
    state = billing.learner_status(purchase)
    return MeCheckoutStatusResponse(
        reference=purchase.reference,
        tier=purchase.tier_key,
        status=state,
        period_end=purchase.period_end if state == "success" else None,
        payment_url=purchase.checkout_url if state == "abandoned" else None,
        paid_twice=(
            await billing.paired_with(session, purchase) is not None if state == "success" else None
        ),
    )


async def _ask_paystack(service: PaymentService, session, purchase: MePurchase) -> bool:
    """Bring a purchase up to date with Paystack. False if Paystack could not say."""

    try:
        await service.recheck_individual(purchase.reference)
    except Exception:
        logger.warning(
            "Could not recheck /me payment %s with Paystack", purchase.reference, exc_info=True
        )
        return False
    await session.refresh(purchase)
    return True


@router.get(
    "/me/subscription", response_model=MeSubscriptionResponse, response_model_exclude_none=True
)
async def me_subscription(
    principal: PrincipalDependency, session: DatabaseSession, request: Request
) -> MeSubscriptionResponse:
    # Waiting payments are asked about first: one Paystack has just confirmed
    # changes the tier below. If Paystack cannot be reached the payment stays
    # shown as waiting, the side that never invites a second payment.
    waiting = await billing.still_waiting(session, principal.user_id)
    service = getattr(request.app.state, "payment_service", None)
    if waiting and isinstance(service, PaymentService) and service.configured:
        for purchase in waiting:
            await _ask_paystack(service, session, purchase)
    still = next((purchase for purchase in waiting if purchase.status == "pending"), None)
    current = await billing.subscription_for(session, principal.user_id)
    twice = await billing.unseen_double_payment(session, principal.user_id)
    first = await billing.paired_with(session, twice) if twice else None
    return MeSubscriptionResponse(
        tier=current.tier.key,
        period_end=current.period_end,
        renewal_reminder_sent_at=current.reminder_sent_at,
        pending_payment=(
            MePendingPayment(reference=still.reference, tier=still.tier_key) if still else None
        ),
        double_payment=(
            MeDoublePayment(
                references=[r for r in (first and first.reference, twice.reference) if r],
                tier=twice.tier_key,
                period_end=current.period_end,
            )
            if twice
            else None
        ),
    )


@router.post("/me/subscription/double-payment/seen", status_code=status.HTTP_204_NO_CONTENT)
async def me_double_payment_seen(principal: PrincipalDependency, session: DatabaseSession) -> None:
    """The learner has read that both payments came through. Idempotent."""

    await session.execute(
        update(MePurchase)
        .where(
            MePurchase.learner_id == principal.user_id,
            MePurchase.double_paid_at.is_not(None),
            MePurchase.double_paid_seen_at.is_(None),
        )
        .values(double_paid_seen_at=datetime.now(UTC))
    )
    await session.commit()
