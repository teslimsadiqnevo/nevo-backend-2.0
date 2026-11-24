"""GET /me/usage: lessons used this month, the allowance, and when it resets.

A first-class answer, not something the app derives (/me Phase 3).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import User
from nevo.me.usage import usage_for

router = APIRouter(prefix="/api/v1", tags=["me"])


class UsageResponse(CamelResponse):
    tier: str
    used: int
    allowance: int
    remaining: int
    #: The first moment of next month, Lagos time. Nothing rolls over.
    resets_at: datetime


@router.get("/me/usage", response_model=UsageResponse)
async def my_usage(principal: PrincipalDependency, session: DatabaseSession) -> UsageResponse:
    user = await session.get(User, principal.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
    usage = await usage_for(session, user)
    return UsageResponse(
        tier=usage.tier.key,
        used=usage.used,
        allowance=usage.allowance,
        remaining=usage.remaining,
        resets_at=usage.resets_at,
    )
