from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from nevo.api import media_ops
from nevo.api.dependencies import database_session

KEY = "test-ops-report-key-with-at-least-32-characters"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPS_REPORT_KEY", KEY)
    engine = create_async_engine("postgresql+asyncpg://test:test@127.0.0.1:1/not_used")
    session = SimpleNamespace(bind=engine, scalar=AsyncMock(return_value=0))

    async def db():
        yield session

    app = FastAPI()
    app.include_router(media_ops.router)
    app.dependency_overrides[database_session] = db
    now = datetime.now(UTC)
    report = {
        "from": (now - timedelta(days=1)).isoformat(),
        "until": now.isoformat(),
        "trackingStartedAt": now.isoformat(),
        "groups": [
            {
                "medium": "audio",
                "provider": "yarngpt",
                "model": "tts",
                "operation": "synthesis",
                "runs": 0,
                "cacheHits": 0,
                "assetWrites": 0,
                "calls": 3,
                "retries": 1,
                "failed": 0,
                "unfinished": 0,
                "unknownCostCalls": 3,
                "usageTotals": {"characters": 3000},
                "uniqueAcceptedCharacters": 2000,
                "estimatedCost": {},
            }
        ],
        "distinctAssetsWrittenInWindow": {"audio": 2},
        "currentAssetInventory": {"audio": {"references": 3, "distinctReferencedAssets": 2}},
        "inventoryBasis": "Current references",
        "costBasis": "Estimated, not invoice",
        "historicalCallsReconstructed": False,
    }
    monkeypatch.setattr(media_ops, "report", AsyncMock(return_value=report))
    with TestClient(app) as test_client:
        yield SimpleNamespace(
            http=test_client, session=session, data=report, report=media_ops.report
        )


def test_no_school_token_can_read_platform_costs(client):
    for headers in (
        {},
        {"Authorization": "Bearer school-admin-token"},
        {"X-Nevo-Ops-Key": "wrong"},
    ):
        response = client.http.get("/api/ops/media-usage", headers=headers)
        assert response.status_code == 401
    client.report.assert_not_awaited()


def test_report_requires_configuration(client, monkeypatch):
    monkeypatch.setenv("OPS_REPORT_KEY", "")
    response = client.http.get("/api/ops/media-usage", headers={"X-Nevo-Ops-Key": KEY})
    assert response.status_code == 503


def test_json_report_is_typed_and_available_to_ops(client):
    response = client.http.get("/api/ops/media-usage", headers={"X-Nevo-Ops-Key": KEY})
    assert response.status_code == 200, response.text
    assert response.json()["groups"][0]["calls"] == 3
    assert response.json()["groups"][0]["unknownCostCalls"] == 3
    assert response.json()["historicalCallsReconstructed"] is False
    schema = client.http.get("/openapi.json").json()["components"]["schemas"]
    assert (
        "UsageReport" in schema and "uniqueAcceptedCharacters" in schema["UsageGroup"]["properties"]
    )


def test_browser_view_escapes_data_and_never_embeds_key(client):
    client.data["groups"][0]["model"] = "<script>alert(1)</script>"
    response = client.http.get("/api/ops/media-usage/view", auth=("ops", KEY))
    assert response.status_code == 200, response.text
    assert "text/html" in response.headers["content-type"]
    assert "&lt;script&gt;" in response.text and "<script>" not in response.text
    assert "Unpriced calls" in response.text and "Referenced assets" in response.text
    assert KEY not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_view_accepts_legacy_timestamps_and_calendar_dates(client):
    for start, end in (
        ("2026-10-20T12:30:00+00:00", "2026-10-22T15:30:00+00:00"),
        ("2026-10-20", "2026-10-22"),
    ):
        response = client.http.get(
            "/api/ops/media-usage/view",
            params={"from": start, "until": end},
            auth=("ops", KEY),
        )
        assert response.status_code == 200, response.text
        assert 'type="date"' in response.text


def cycle():
    now = datetime.now(UTC) - timedelta(seconds=1)
    return {
        "from": (now - timedelta(days=1)).isoformat(),
        "until": now.isoformat(),
        "paidAmount": "500",
        "refunds": "100",
        "currency": "NGN",
        "fullyConsumed": True,
        "zeroOpeningBalance": True,
        "exclusiveNarrationUse": True,
        "trackingCoveredWholeCycle": True,
    }


def test_effective_rate_uses_deduplicated_characters_and_is_not_official(client):
    response = client.http.post(
        "/api/ops/media-usage/effective-rate", json=cycle(), headers={"X-Nevo-Ops-Key": KEY}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["observedCharacters"] == 2000
    assert Decimal(data["netPaidAmount"]) == 400
    assert Decimal(data["effectivePer1000Characters"]) == 200
    assert data["officialProviderRate"] is False and data["appliesAutomatically"] is False


@pytest.mark.parametrize(
    "field",
    ["fullyConsumed", "zeroOpeningBalance", "exclusiveNarrationUse", "trackingCoveredWholeCycle"],
)
def test_unreconciled_or_shared_cycle_cannot_be_claimed(client, field):
    payload = cycle()
    payload[field] = False
    response = client.http.post(
        "/api/ops/media-usage/effective-rate", json=payload, headers={"X-Nevo-Ops-Key": KEY}
    )
    assert response.status_code == 422


def test_uncertain_calls_and_empty_period_cannot_produce_a_rate(client):
    client.session.scalar.return_value = 1
    response = client.http.post(
        "/api/ops/media-usage/effective-rate", json=cycle(), headers={"X-Nevo-Ops-Key": KEY}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "usage_cycle_requires_reconciliation"
    client.session.scalar.return_value = 0
    client.data["groups"] = []
    response = client.http.post(
        "/api/ops/media-usage/effective-rate", json=cycle(), headers={"X-Nevo-Ops-Key": KEY}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_observed_characters"


def test_invalid_report_window_is_refused(client):
    response = client.http.get(
        "/api/ops/media-usage?from=2026-10-20T00:00:00", headers={"X-Nevo-Ops-Key": KEY}
    )
    assert response.status_code == 422
