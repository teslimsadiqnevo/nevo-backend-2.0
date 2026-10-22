"""Durable, content-free accounting at the media provider boundary."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Any, ParamSpec, Protocol
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary

import httpx
import sqlalchemy as sa
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine

from nevo.core.config import get_settings
from nevo.db.models.media_usage import media_usage_events as events
from nevo.db.session import create_engine

# Standard direct-API prices checked 2026-10-22; contracts can override them.
# https://developers.openai.com/api/docs/pricing
# https://platform.claude.com/docs/en/about-claude/pricing
DEFAULT_PRICES: dict[str, dict[str, Any]] = {
    "openai:gpt-image-2": {
        "currency": "USD",
        "input_text_per_million": "5",
        "input_image_per_million": "8",
        "output_per_million": "30",
    },
    "anthropic:claude-opus-4-8": {
        "currency": "USD",
        "input_per_million": "5",
        "output_per_million": "25",
        "cache_read_per_million": ".5",
        "cache_write_per_million": "6.25",
    },
    "anthropic:claude-haiku-4-5": {
        "currency": "USD",
        "input_per_million": "1",
        "output_per_million": "5",
        "cache_read_per_million": ".1",
        "cache_write_per_million": "1.25",
    },
}


class MediaUsageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    media_pricing_json: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def effective_prices(self) -> dict[str, dict[str, Any]]:
        return {**DEFAULT_PRICES, **self.media_pricing_json}

    @field_validator("media_pricing_json")
    @classmethod
    def valid_prices(cls, value: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        allowed = {
            "currency",
            "per_1000_characters",
            "per_image",
            "input_per_million",
            "input_text_per_million",
            "input_image_per_million",
            "output_per_million",
            "cache_read_per_million",
            "cache_write_per_million",
        }
        for rates in value.values():
            if not isinstance(rates, dict) or set(rates) - allowed:
                raise ValueError("Unsupported media price fields")
            currency = rates.get("currency", "")
            if (
                not isinstance(currency, str)
                or len(currency) != 3
                or not currency.isascii()
                or not currency.isalpha()
                or currency != currency.upper()
            ):
                raise ValueError("Media prices require a three-letter currency")
            for key, price in rates.items():
                if key == "currency":
                    continue
                try:
                    amount = Decimal(str(price))
                except InvalidOperation as error:
                    raise ValueError("Media prices must be numeric") from error
                if not amount.is_finite() or amount < 0:
                    raise ValueError("Media prices must be finite and nonnegative")
        return value


class MediaLedger:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def start(self, values: dict[str, Any]) -> UUID:
        event_id = uuid4()
        async with self.engine.begin() as connection:
            await connection.execute(
                events.insert().values(
                    id=event_id,
                    occurred_at=datetime.now(UTC),
                    status="started",
                    usage={},
                    pricing={},
                    **values,
                )
            )
        return event_id

    async def finish(self, event_id: UUID, **values: Any) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                events.update()
                .where(events.c.id == event_id)
                .values(
                    completed_at=datetime.now(UTC),
                    **values,
                )
            )


class Ledger(Protocol):
    async def start(self, values: dict[str, Any]) -> UUID: ...

    async def finish(self, event_id: UUID, **values: Any) -> None: ...


_ledgers: WeakKeyDictionary[asyncio.AbstractEventLoop, MediaLedger] = WeakKeyDictionary()


def default_ledger() -> MediaLedger:
    loop = asyncio.get_running_loop()
    if loop not in _ledgers:
        _ledgers[loop] = MediaLedger(create_engine(get_settings().database_url))
    return _ledgers[loop]


async def close_ledger() -> None:
    ledger = _ledgers.pop(asyncio.get_running_loop(), None)
    if ledger is not None:
        await ledger.engine.dispose()


@dataclass
class Run:
    id: UUID
    medium: str
    ledger: Ledger
    prices: dict[str, dict[str, Any]]
    attempts: dict[tuple[str, str, str], int] = field(default_factory=dict)
    cache_hit: bool = False


current_run: ContextVar[Run | None] = ContextVar("media_usage_run", default=None)


P = ParamSpec("P")
Generation = Callable[P, Awaitable[dict[str, object]]]


def tracked_generation(medium: str) -> Callable[[Generation[P]], Generation[P]]:
    def decorate(function: Generation[P]) -> Generation[P]:
        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> dict[str, object]:
            ledger = default_ledger()
            run = Run(uuid4(), medium, ledger, MediaUsageSettings().effective_prices())
            event_id = await ledger.start(
                {"run_id": run.id, "kind": "generation", "medium": medium}
            )
            token = current_run.set(run)
            try:
                result = await function(*args, **kwargs)
                await ledger.finish(
                    event_id,
                    status="cache_hit" if run.cache_hit else "succeeded",
                    asset_path=result.get("storagePath"),
                )
                return result
            except BaseException as error:
                await asyncio.shield(
                    ledger.finish(
                        event_id,
                        status="cancelled"
                        if isinstance(error, asyncio.CancelledError)
                        else "failed",
                        error_type=type(error).__name__,
                    )
                )
                raise
            finally:
                current_run.reset(token)

        return wrapped

    return decorate


def cache_hit() -> None:
    if run := current_run.get():
        run.cache_hit = True


def usage_counts(body: Any) -> dict[str, int]:
    raw = body.get("usage", {}) if isinstance(body, dict) else {}
    if not isinstance(raw, dict):
        return {}
    result: dict[str, int] = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        if isinstance(raw.get(key), int) and raw[key] >= 0:
            result[key] = raw[key]
    details = raw.get("input_tokens_details", {})
    if isinstance(details, dict):
        for key in ("text_tokens", "image_tokens"):
            if isinstance(details.get(key), int) and details[key] >= 0:
                result[key] = details[key]
    return result


def estimate(usage: dict[str, int], rates: dict[str, Any], operation: str) -> Decimal | None:
    """Unknown is NULL, never a guessed zero or an invoice claim."""
    if not rates:
        return None
    if operation == "synthesis" and "per_1000_characters" in rates:
        return Decimal(usage["characters"]) * Decimal(str(rates["per_1000_characters"])) / 1000
    if operation == "image_generation" and "per_image" in rates:
        return Decimal(str(rates["per_image"]))
    if not {"input_tokens", "output_tokens"} <= usage.keys():
        return None
    components: list[tuple[str, str]] = []
    if {"text_tokens", "image_tokens"} <= usage.keys():
        if usage["text_tokens"] + usage["image_tokens"] != usage["input_tokens"]:
            return None
        components.extend(
            (("text_tokens", "input_text_per_million"), ("image_tokens", "input_image_per_million"))
        )
    else:
        components.append(("input_tokens", "input_per_million"))
    components.extend(
        (
            ("output_tokens", "output_per_million"),
            ("cache_read_input_tokens", "cache_read_per_million"),
            ("cache_creation_input_tokens", "cache_write_per_million"),
        )
    )
    total = Decimal(0)
    for count, rate in components:
        if usage.get(count, 0):
            if rate not in rates:
                return None
            total += Decimal(usage[count]) * Decimal(str(rates[rate])) / 1_000_000
    return total


async def provider_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider: str,
    model: str,
    operation: str,
    retry_number: int | None = None,
    **kwargs: Any,
) -> httpx.Response:
    call: Callable[..., Awaitable[httpx.Response]] = getattr(client, method.lower())
    run = current_run.get()
    if run is None:
        # Safety also serves non-media calls, which have their own gateway accounting.
        return await call(url, **kwargs)
    key = (provider, model, operation)
    run.attempts[key] = run.attempts.get(key, 0) + 1
    attempt = retry_number or run.attempts[key]
    event_id = await run.ledger.start(
        {
            "run_id": run.id,
            "kind": "provider_call",
            "medium": run.medium,
            "provider": provider,
            "model": model,
            "operation": operation,
            "attempt": attempt,
        }
    )
    try:
        response = await call(url, **kwargs)
    except BaseException as error:
        await asyncio.shield(
            run.ledger.finish(
                event_id,
                status="cancelled"
                if isinstance(error, asyncio.CancelledError)
                else "transport_error",
                error_type=type(error).__name__,
            )
        )
        raise
    try:
        body = response.json()
    except (ValueError, UnicodeDecodeError):
        body = {}
    counts = usage_counts(body)
    if operation == "synthesis":
        counts["characters"] = len((kwargs.get("json") or {}).get("text", ""))
    rates = run.prices.get(f"{provider}:{model}", {})
    charge = body.get("job_id") if isinstance(body, dict) else None
    request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
    if charge is None and request_id:
        charge = request_id
    cost = estimate(counts, rates, operation) if not response.is_error else None
    if operation in {"voice_catalogue", "job_read"}:
        cost = Decimal(0)
    await run.ledger.finish(
        event_id,
        status="http_error" if response.is_error else "succeeded",
        http_status=response.status_code,
        request_id=(request_id or "")[:160] or None,
        charge_key=f"{provider}:{str(charge)[:160]}" if charge else None,
        usage=counts,
        pricing=rates,
        currency=rates.get("currency"),
        estimated_cost=cost,
    )
    return response


async def report(engine: AsyncEngine, since: datetime, until: datetime) -> dict[str, Any]:
    async with engine.connect() as connection:
        rows = (
            (
                await connection.execute(
                    sa.select(events).where(
                        events.c.occurred_at >= since,
                        events.c.occurred_at < until,
                    )
                )
            )
            .mappings()
            .all()
        )
        assets = (
            await connection.execute(
                sa.text(
                    "SELECT audio_variant, visual_variant, calculation_variant FROM lesson_segments"
                )
            )
        ).all()
        started = await connection.scalar(sa.select(sa.func.min(events.c.occurred_at)))
        ranked = (
            sa.select(
                events.c.id,
                sa.func.row_number()
                .over(
                    partition_by=events.c.charge_key,
                    order_by=(events.c.occurred_at, events.c.id),
                )
                .label("rank"),
            )
            .where(events.c.charge_key.is_not(None), events.c.status == "succeeded")
            .subquery()
        )
        first_charge_ids: set[UUID] = set(
            (await connection.execute(sa.select(ranked.c.id).where(ranked.c.rank == 1))).scalars()
        )
    paths: dict[str, set[str]] = {"audio": set(), "image": set()}
    references = {"audio": 0, "image": 0}

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for medium, field_name in (("audio", "audioUrl"), ("image", "imageUrl")):
                if value.get(field_name):
                    paths[medium].add(value.get("storagePath") or value[field_name])
                    references[medium] += 1
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for asset in assets:
        for variant in asset:
            collect(variant)
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    written: dict[str, set[str]] = {"audio": set(), "image": set()}
    for row in rows:
        key = (row["medium"], row["provider"], row["model"], row["operation"])
        group = groups.setdefault(
            key,
            {
                "medium": key[0],
                "provider": key[1],
                "model": key[2],
                "operation": key[3],
                "runs": 0,
                "cacheHits": 0,
                "assetWrites": 0,
                "calls": 0,
                "retries": 0,
                "failed": 0,
                "unfinished": 0,
                "unknownCostCalls": 0,
                "usageTotals": {},
                "uniqueAcceptedCharacters": 0,
                "estimatedCost": {},
            },
        )
        if row["kind"] == "generation":
            group["runs"] += 1
            group["cacheHits"] += row["status"] == "cache_hit"
            if row["status"] == "succeeded" and row["asset_path"]:
                group["assetWrites"] += 1
                written[row["medium"]].add(row["asset_path"])
        else:
            group["calls"] += 1
            group["retries"] += row["attempt"] > 1
            group["unknownCostCalls"] += row["estimated_cost"] is None
            for unit, quantity in row["usage"].items():
                group["usageTotals"][unit] = group["usageTotals"].get(unit, 0) + quantity
            first_charge = row["charge_key"] is None or row["id"] in first_charge_ids
            if first_charge and row["status"] == "succeeded":
                group["uniqueAcceptedCharacters"] += row["usage"].get("characters", 0)
            if row["estimated_cost"] is not None and first_charge:
                if currency := row["currency"]:
                    costs = group["estimatedCost"]
                    costs[currency] = costs.get(currency, Decimal(0)) + row["estimated_cost"]
        group["failed"] += row["status"] in {"failed", "transport_error", "http_error", "cancelled"}
        group["unfinished"] += row["status"] == "started"
    return {
        "from": since.isoformat(),
        "until": until.isoformat(),
        "groups": list(groups.values()),
        "trackingStartedAt": started.isoformat() if started else None,
        "distinctAssetsWrittenInWindow": {medium: len(items) for medium, items in written.items()},
        "currentAssetInventory": {
            medium: {"references": references[medium], "distinctReferencedAssets": len(items)}
            for medium, items in paths.items()
        },
        "inventoryBasis": (
            "Current database references, not a bucket-existence check; not date-filtered"
        ),
        "costBasis": "estimated, not invoice; unknown costs excluded; currencies not converted",
        "historicalCallsReconstructed": False,
    }


def json_report(value: Any) -> str:
    return json.dumps(value, default=str, indent=2)
