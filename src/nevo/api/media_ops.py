"""Private platform-wide media accounting, never a school-admin permission."""

import secrets
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from html import escape
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nevo.api.dependencies import DatabaseSession
from nevo.db.models.media_usage import media_usage_events as events
from nevo.ops.config import OpsSettings
from nevo.ops.media_usage import report

router = APIRouter(prefix="/api/ops/media-usage", tags=["intelligence"])
basic_auth = HTTPBasic(auto_error=False)


def ops_access(
    response: Response,
    key: Annotated[str | None, Header(alias="X-Nevo-Ops-Key")] = None,
    basic: Annotated[HTTPBasicCredentials | None, Depends(basic_auth)] = None,
) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Authorization, X-Nevo-Ops-Key"
    expected = OpsSettings().report_key
    if expected is None:
        raise HTTPException(503, detail={"code": "ops_reports_not_configured"})
    candidate = key or (basic.password if basic and basic.username == "ops" else "")
    if not secrets.compare_digest(candidate.encode(), expected.get_secret_value().encode()):
        raise HTTPException(
            401,
            detail={"code": "ops_access_required"},
            headers={"WWW-Authenticate": 'Basic realm="Nevo Ops"'},
        )


class UsageGroup(BaseModel):
    medium: str
    provider: str | None
    model: str | None
    operation: str | None
    runs: int
    cacheHits: int
    assetWrites: int
    calls: int
    retries: int
    failed: int
    unfinished: int
    unknownCostCalls: int
    usageTotals: dict[str, int]
    uniqueAcceptedCharacters: int
    estimatedCost: dict[str, Decimal]


class AssetCount(BaseModel):
    references: int
    distinctReferencedAssets: int


class UsageReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    since: datetime = Field(alias="from")
    until: datetime
    groups: list[UsageGroup]
    trackingStartedAt: datetime | None
    distinctAssetsWrittenInWindow: dict[str, int]
    currentAssetInventory: dict[str, AssetCount]
    inventoryBasis: str
    costBasis: str
    historicalCallsReconstructed: Literal[False]


def window(since: datetime | None, until: datetime | None) -> tuple[datetime, datetime]:
    end = until or datetime.now(UTC)
    start = since or end - timedelta(days=30)
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or not start < end
        or end - start > timedelta(days=366)
    ):
        raise HTTPException(
            422,
            detail={
                "code": "invalid_reporting_range",
                "message": "Use timezone-aware dates spanning at most 366 days.",
            },
        )
    return start, end


def engine_for(session: AsyncSession) -> AsyncEngine:
    if not isinstance(session.bind, AsyncEngine):
        raise HTTPException(503, detail={"code": "database_unavailable"})
    return session.bind


@router.get("", response_model=UsageReport, dependencies=[Depends(ops_access)])
async def media_usage(
    session: DatabaseSession,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: datetime | None = None,
) -> UsageReport:
    start, end = window(since, until)
    return UsageReport.model_validate(await report(engine_for(session), start, end))


def report_html(data: UsageReport) -> str:
    rows = []
    for group in data.groups:
        costs = ", ".join(
            f"{currency} {value:f}" for currency, value in group.estimatedCost.items()
        )
        cells = [
            group.medium,
            group.provider or "Generation runs",
            group.model or "-",
            group.operation or "Asset outcome",
            group.runs,
            group.cacheHits,
            group.assetWrites,
            group.calls,
            group.retries,
            group.failed,
            group.unfinished,
            group.uniqueAcceptedCharacters,
            costs or "-",
            group.unknownCostCalls,
        ]
        rows.append("<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in cells) + "</tr>")
    head = [
        "Media",
        "Provider",
        "Model",
        "Operation",
        "Runs",
        "Cache hits",
        "Writes",
        "Calls",
        "Retries",
        "Failures",
        "Unfinished",
        "Unique accepted characters",
        "Estimated cost",
        "Unpriced calls",
    ]
    inventory = "".join(
        f"<tr><td>{escape(medium)}</td><td>{item.references}</td>"
        f"<td>{item.distinctReferencedAssets}</td>"
        f"<td>{data.distinctAssetsWrittenInWindow.get(medium, 0)}</td></tr>"
        for medium, item in data.currentAssetInventory.items()
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nevo media usage</title><style>
body{{margin:0;padding:28px;background:#f7f1e6;color:#2b2b2f;font:14px system-ui,sans-serif}}
h1{{font-size:24px;margin:0 0 20px}}h2{{font-size:18px;margin-top:28px}}
form{{display:flex;flex-wrap:wrap;gap:16px;align-items:end;margin-bottom:24px}}
label{{display:grid;gap:6px}}input,button{{font:inherit;padding:9px;border:1px solid #3b3f6e;
border-radius:4px;background:#ede8dc;color:#2b2b2f}}button{{cursor:pointer}}
.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:10px;border-bottom:1px solid #9a9ccb;white-space:nowrap}}
th{{background:#3b3f6e;color:#f7f1e6}}tbody tr:nth-child(even){{background:#ede8dc}}
p{{max-width:1000px;line-height:1.5}}@media print{{form{{display:none}}body{{padding:0}}}}
</style></head><body><h1>Nevo media usage</h1>
<form method="get"><label>From (UTC)<input type="date" name="from"
value="{data.since.date().isoformat()}" required></label>
<label>Through (UTC)<input type="date" name="until"
value="{(data.until - timedelta(microseconds=1)).date().isoformat()}" required></label>
<button type="submit">Refresh report</button></form>
<p>Recorded since: {escape(str(data.trackingStartedAt or "No usage recorded yet"))}.
Costs are estimates, not invoices. Unpriced calls are not treated as free.
Currencies are kept separate. Calls before tracking began are not reconstructed.</p>
<h2>Generation and provider calls</h2><div class="scroll"><table><thead><tr>
{"".join(f'<th scope="col">{escape(label)}</th>' for label in head)}</tr></thead><tbody>
{"".join(rows) or '<tr><td colspan="14">No usage recorded in this period.</td></tr>'}
</tbody></table></div><h2>Referenced assets</h2><div class="scroll"><table>
<thead><tr><th>Media</th><th>References now</th><th>Distinct assets now</th>
<th>Distinct assets written in period</th></tr></thead><tbody>{inventory}</tbody></table></div>
<p>{escape(data.inventoryBasis)}. This is not a complete bucket inventory.</p>
</body></html>"""


@router.get("/view", response_class=HTMLResponse, dependencies=[Depends(ops_access)])
async def media_usage_view(
    session: DatabaseSession,
    since: Annotated[date | datetime | None, Query(alias="from")] = None,
    until: date | datetime | None = None,
) -> HTMLResponse:
    if isinstance(since, datetime):
        since = since.astimezone(UTC).date() if since.tzinfo else since.date()
    if isinstance(until, datetime):
        until = until.astimezone(UTC).date() if until.tzinfo else until.date()
    end_date = until or datetime.now(UTC).date()
    start_date = since or (end_date - timedelta(days=29))
    if end_date == date.max:
        raise HTTPException(422, detail={"code": "invalid_reporting_range"})
    start = datetime.combine(start_date, time.min, tzinfo=UTC)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
    data = await media_usage(session, start, end)
    return HTMLResponse(
        report_html(data),
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "form-action 'self'; frame-ancestors 'none'"
            ),
            "Vary": "Authorization, X-Nevo-Ops-Key",
        },
    )


class RateCycle(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    since: datetime = Field(alias="from")
    until: datetime
    paidAmount: Decimal = Field(gt=0, max_digits=16, decimal_places=6)
    refunds: Decimal = Field(default=Decimal(0), ge=0, max_digits=16, decimal_places=6)
    currency: str = Field(pattern="^[A-Z]{3}$")
    fullyConsumed: Literal[True]
    zeroOpeningBalance: Literal[True]
    exclusiveNarrationUse: Literal[True]
    trackingCoveredWholeCycle: Literal[True]


class EffectiveRate(BaseModel):
    observedCharacters: int
    netPaidAmount: Decimal
    currency: str
    effectivePer1000Characters: Decimal
    basis: Literal["effective_cost_per_observed_accepted_character"]
    officialProviderRate: Literal[False] = False
    appliesAutomatically: Literal[False] = False


@router.post("/effective-rate", response_model=EffectiveRate, dependencies=[Depends(ops_access)])
async def effective_narration_rate(payload: RateCycle, session: DatabaseSession) -> EffectiveRate:
    start, end = window(payload.since, payload.until)
    if end > datetime.now(UTC) or payload.refunds >= payload.paidAmount:
        raise HTTPException(422, detail={"code": "invalid_closed_cycle"})
    uncertain = await session.scalar(
        select(func.count())
        .select_from(events)
        .where(
            events.c.provider == "yarngpt",
            events.c.operation == "synthesis",
            events.c.occurred_at >= start,
            events.c.occurred_at < end,
            (events.c.status.in_(["started", "transport_error", "cancelled"]))
            | (events.c.http_status >= 500)
            | ((events.c.status == "succeeded") & events.c.charge_key.is_(None)),
        )
    )
    if uncertain:
        raise HTTPException(409, detail={"code": "usage_cycle_requires_reconciliation"})
    data = await report(engine_for(session), start, end)
    characters = sum(
        group["uniqueAcceptedCharacters"]
        for group in data["groups"]
        if group["provider"] == "yarngpt" and group["operation"] == "synthesis"
    )
    if not characters:
        raise HTTPException(409, detail={"code": "no_observed_characters"})
    net = payload.paidAmount - payload.refunds
    return EffectiveRate(
        observedCharacters=characters,
        netPaidAmount=net,
        currency=payload.currency,
        effectivePer1000Characters=net * 1000 / characters,
        basis="effective_cost_per_observed_accepted_character",
    )
