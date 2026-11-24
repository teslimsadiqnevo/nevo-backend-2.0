"""/me Phase 4: tiers, checkout and the learner's subscription.

Checkout is closed (404, as if absent) unless ME_BILLING_ENABLED is set -
never opened by a Paystack key being present. The month is granted by the
verified webhook (POST /api/billing/payments/webhook, which already handles
school receipts), never by the learner arriving back from Paystack.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.response_models import CamelResponse
from nevo.consent.guardian import upload_blocked_by_consent
from nevo.core.config import get_settings
from nevo.db.models.account import User
from nevo.me import billing, tiers
from nevo.payments.errors import PaymentError
from nevo.payments.service import PaymentService

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


class MeCheckoutResponse(CamelResponse):
    authorization_url: str
    reference: str


class MeSubscriptionResponse(CamelResponse):
    tier: str
    #: When paid access ends, renewals already bought included. Omitted on
    #: the free tier. Nothing renews by itself.
    period_end: datetime | None = None
    renewal_reminder_sent_at: datetime | None = None
    auto_renews: Literal[False] = False


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
    tier = tiers.by_key(payload.tier)
    assert tier is not None
    try:
        checkout = await billing.start_checkout(
            session,
            service.client,
            learner,
            tier,
            callback_url=str(service.settings.me_callback_url),
        )
    except billing.CheckoutRefused as refusal:
        raise HTTPException(refusal.status_code, detail={"code": refusal.code}) from refusal
    except PaymentError as error:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail={"code": error.code}
        ) from error
    return MeCheckoutResponse(
        authorization_url=checkout.authorization_url, reference=checkout.reference
    )


@router.get(
    "/me/subscription", response_model=MeSubscriptionResponse, response_model_exclude_none=True
)
async def me_subscription(
    principal: PrincipalDependency, session: DatabaseSession
) -> MeSubscriptionResponse:
    current = await billing.subscription_for(session, principal.user_id)
    return MeSubscriptionResponse(
        tier=current.tier.key,
        period_end=current.period_end,
        renewal_reminder_sent_at=current.reminder_sent_at,
    )
