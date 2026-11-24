"""The /me tiers: what each costs and how many lessons a month it allows.

Read by the upload gate (Phase 3) and by GET /me/tiers and checkout (Phase 4),
so the prices live here and nowhere in the app.

Three lessons free, twelve at N2,499, twenty-five at N6,999, per calendar
month in Lagos time, no roll-over. Above twenty-five a learner is routed to
contact, not offered a fourth price.

N2,499 IS LOAD-BEARING - DO NOT ROUND IT UP. Paystack's local fee is 1.5%,
about N37 at this price. From N2,500 a flat N100 is added, a further 4%,
taking the total to about 5.5% - nearly four times the rate. Ruling C4,
24 November 2026. Moving this by N5 quadruples what every sale costs.

Tier keys are neutral identifiers. What a learner reads them as is Lydia's.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    key: str
    lessons_per_month: int
    #: Whole naira. None for the free tier.
    price_naira: int | None


FREE = Tier(key="free", lessons_per_month=3, price_naira=None)
TWELVE = Tier(key="monthly_12", lessons_per_month=12, price_naira=2_499)
TWENTY_FIVE = Tier(key="monthly_25", lessons_per_month=25, price_naira=6_999)

TIERS: tuple[Tier, ...] = (FREE, TWELVE, TWENTY_FIVE)
TOP = TWENTY_FIVE


def by_key(key: str) -> Tier | None:
    return next((tier for tier in TIERS if tier.key == key), None)
