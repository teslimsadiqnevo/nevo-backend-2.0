import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from nevo.ops.media_usage import (
    MediaLedger,
    MediaUsageSettings,
    Run,
    cache_hit,
    current_run,
    estimate,
    events,
    provider_request,
    report,
    tracked_generation,
    usage_counts,
)


def test_prices_require_currency_nonnegative_and_known_units():
    for config in (
        {"x": {"per_image": 1}},
        {"x": {"currency": "USD", "per_image": -1}},
        {"x": {"currency": "USD", "per_image": "NaN"}},
        {"x": {"currency": "USD", "per_image": "not a number"}},
        {"x": {"currency": 123, "per_image": 1}},
        {"x": {"currency": "USD", "per_second": 1}},
    ):
        with pytest.raises(ValidationError):
            MediaUsageSettings(media_pricing_json=config)


def test_costs_use_decimal_and_never_invent_missing_prices():
    assert estimate({"characters": 1200}, {"per_1000_characters": "2.5"}, "synthesis") == 3
    assert estimate({}, {}, "image_generation") is None
    assert estimate({}, {"per_image": ".04"}, "image_generation") == Decimal(".04")
    usage = {"input_tokens": 100, "output_tokens": 20, "text_tokens": 40, "image_tokens": 60}
    rates = {"input_text_per_million": 1, "input_image_per_million": 2, "output_per_million": 5}
    assert estimate(usage, rates, "image_generation") == Decimal(".00026")
    assert estimate(usage, {"input_per_million": 1}, "image_generation") is None
    assert (
        estimate(
            {"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 5},
            {"input_per_million": 1, "output_per_million": 1},
            "image_review",
        )
        is None
    )


def test_verified_defaults_and_account_rate_overrides():
    prices = MediaUsageSettings().effective_prices()
    assert prices["openai:gpt-image-2"]["output_per_million"] == "30"
    assert "yarngpt:tts" not in prices
    rates = {"currency": "NGN", "per_1000_characters": "3"}
    assert (
        MediaUsageSettings(media_pricing_json={"yarngpt:tts": rates}).effective_prices()[
            "yarngpt:tts"
        ]
        == rates
    )


def test_usage_only_contains_numeric_accounting_not_content():
    assert usage_counts(
        {
            "usage": {
                "prompt": "secret",
                "input_tokens": 4,
                "input_tokens_details": {"text_tokens": 4, "secret": 9},
            }
        }
    ) == {
        "input_tokens": 4,
        "text_tokens": 4,
    }


async def test_cache_and_failed_storage_are_durable_run_outcomes(media_ledger):
    @tracked_generation("audio")
    async def cached():
        cache_hit()
        return {"storagePath": "audio/hash.mp3"}

    @tracked_generation("image")
    async def failed():
        raise ValueError("secret lesson and credentials")

    await cached()
    with pytest.raises(ValueError):
        await failed()
    rows = list(media_ledger.rows.values())
    assert [r["status"] for r in rows] == ["cache_hit", "failed"]
    assert rows[1]["error_type"] == "ValueError"
    assert "secret" not in str(rows)
    assert current_run.get() is None


async def test_each_provider_attempt_persisted_before_network_and_prices_snapshotted(media_ledger):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        assert len(media_ledger.rows) == calls
        return httpx.Response(
            429 if calls == 1 else 202, json={"job_id": "job-1"}, headers={"x-request-id": "req-1"}
        )

    run = Run(
        uuid4(),
        "audio",
        media_ledger,
        {"yarngpt:tts": {"currency": "NGN", "per_1000_characters": "2"}},
    )
    token = current_run.set(run)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            for attempt in (1, 2):
                await provider_request(
                    client,
                    "POST",
                    "https://provider/tts",
                    provider="yarngpt",
                    model="tts",
                    operation="synthesis",
                    retry_number=attempt,
                    json={"text": "abc", "secret": "do not store"},
                )
    finally:
        current_run.reset(token)
    rows = list(media_ledger.rows.values())
    assert [r["attempt"] for r in rows] == [1, 2]
    assert rows[0]["estimated_cost"] is None
    assert rows[1]["estimated_cost"] == Decimal(".006")
    assert rows[1]["currency"] == "NGN"
    assert rows[1]["charge_key"] == "yarngpt:job-1"
    assert "do not store" not in str(rows)


async def test_transport_failure_and_cancellation_not_lost(media_ledger):
    async def handler(request):
        raise httpx.ReadTimeout("sensitive URL")

    token = current_run.set(Run(uuid4(), "image", media_ledger, {}))
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.ReadTimeout):
                await provider_request(
                    client,
                    "POST",
                    "https://provider/image",
                    provider="openai",
                    model="image",
                    operation="image_generation",
                )
    finally:
        current_run.reset(token)
    assert next(iter(media_ledger.rows.values()))["status"] == "transport_error"

    @tracked_generation("audio")
    async def cancelled():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await cancelled()
    assert list(media_ledger.rows.values())[-1]["status"] == "cancelled"


async def test_ledger_failure_prevents_unmetered_provider_spend(monkeypatch):
    class Broken:
        async def start(self, values):
            raise RuntimeError("database unavailable")

    from nevo.ops import media_usage

    monkeypatch.setattr(media_usage, "default_ledger", Broken)
    reached = False

    @tracked_generation("image")
    async def generate():
        nonlocal reached
        reached = True

    with pytest.raises(RuntimeError):
        await generate()
    assert not reached


@pytest.mark.integration
async def test_audio_adapter_persists_calls_and_cache_hits_on_postgres(monkeypatch):
    url = os.environ.get("NEVO_RUNTIME_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires explicit disposable PostgreSQL URL")
    assert "127.0.0.1:55439/" in url
    from nevo.audio.config import AudioSettings
    from nevo.audio.service import AudioGenerationService
    from nevo.db.session import create_engine
    from nevo.ops import media_usage

    engine = create_engine(url)
    ledger = MediaLedger(engine)
    monkeypatch.setattr(media_usage, "default_ledger", lambda: ledger)
    start = datetime.now(UTC)
    uploaded = False

    def handler(request):
        nonlocal uploaded
        if request.method == "HEAD":
            return httpx.Response(200 if uploaded else 404)
        if request.url.path.endswith("/voices"):
            return httpx.Response(200, json={"voices": [{"name": "test", "default": True}]})
        if request.url.path.endswith("/tts"):
            return httpx.Response(
                200,
                content=b"audio",
                headers={
                    "content-type": "audio/mpeg",
                    "x-request-id": str(uuid4()),
                },
            )
        assert "/storage/" in request.url.path
        uploaded = True
        return httpx.Response(200)

    original = httpx.AsyncClient

    def client(*args, **kwargs):
        return original(*args, **kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    service = AudioGenerationService(
        AudioSettings(
            _env_file=None,
            YARNGPT_API_KEY="test-key",
            YARNGPT_VOICE=None,
            SUPABASE_URL="https://storage.example",
            SUPABASE_SERVICE_ROLE_KEY="test-key",
            SUPABASE_STORAGE_PUBLIC=True,
        )
    )
    try:
        first = await service.generate("Source narration")
        second = await service.generate("Source narration")
        assert first["storagePath"] == second["storagePath"]
        result = await report(engine, start, datetime.now(UTC) + timedelta(seconds=1))
        runs = next(g for g in result["groups"] if g["operation"] is None)
        synthesis = next(g for g in result["groups"] if g["operation"] == "synthesis")
        assert runs["runs"] == 2 and runs["cacheHits"] == 1 and runs["assetWrites"] == 1
        assert synthesis["calls"] == 1 and synthesis["unknownCostCalls"] == 1
        assert synthesis["usageTotals"]["characters"] == len("Source narration")
        assert result["distinctAssetsWrittenInWindow"]["audio"] == 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(events.delete().where(events.c.occurred_at >= start))
        await engine.dispose()


@pytest.mark.integration
async def test_postgres_persistence_reporting_and_job_deduplication():
    url = os.environ.get("NEVO_RUNTIME_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires explicit disposable PostgreSQL URL")
    assert "127.0.0.1:55439/" in url
    from nevo.db.session import create_engine

    engine = create_engine(url)
    ledger = MediaLedger(engine)
    start = datetime.now(UTC)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(events.create, checkfirst=True)
        run_id = uuid4()
        for attempt in (1, 2):
            event_id = await ledger.start(
                {
                    "run_id": run_id,
                    "kind": "provider_call",
                    "medium": "audio",
                    "provider": "yarngpt",
                    "model": "tts",
                    "operation": "synthesis",
                    "attempt": attempt,
                }
            )
            await ledger.finish(
                event_id,
                status="succeeded",
                charge_key=f"test:{run_id}",
                estimated_cost=Decimal(".01"),
                currency="USD",
            )
            if attempt == 1:
                between = datetime.now(UTC)
        pending = await ledger.start({"run_id": run_id, "kind": "generation", "medium": "audio"})
        # A fresh recorder can read records from the earlier instance.
        result = await report(engine, start, datetime.now(UTC) + timedelta(seconds=1))
        group = next(g for g in result["groups"] if g["operation"] == "synthesis")
        assert group["calls"] == 2 and group["retries"] == 1
        assert group["estimatedCost"] == {"USD": Decimal(".01")}
        assert sum(g["unfinished"] for g in result["groups"]) == 1
        assert result["historicalCallsReconstructed"] is False
        later = await report(engine, between, datetime.now(UTC) + timedelta(seconds=1))
        assert (
            next(g for g in later["groups"] if g["operation"] == "synthesis")["estimatedCost"] == {}
        )
        await MediaLedger(engine).finish(pending, status="succeeded")
    finally:
        async with engine.begin() as connection:
            await connection.execute(events.delete().where(events.c.occurred_at >= start))
        await engine.dispose()
