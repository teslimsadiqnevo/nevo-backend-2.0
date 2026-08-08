import asyncio

import httpx
import pytest

from nevo.ops.keepalive import SelfPingLoop


def client_with(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


async def test_self_ping_loop_requests_health_repeatedly() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"status": "ok"})

    loop = SelfPingLoop(
        health_url="https://nevo-backend.example.com/health",
        interval_seconds=0.01,
        client=client_with(handler),
    )

    loop.start()
    for _ in range(50):
        if len(calls) >= 3:
            break
        await asyncio.sleep(0.01)
    await loop.stop()

    assert len(calls) >= 3
    assert all(url == "https://nevo-backend.example.com/health" for url in calls)


async def test_self_ping_loop_survives_request_failures() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("boom", request=request)

    loop = SelfPingLoop(
        health_url="https://nevo-backend.example.com/health",
        interval_seconds=0.01,
        client=client_with(handler),
    )

    loop.start()
    for _ in range(50):
        if calls >= 2:
            break
        await asyncio.sleep(0.01)
    await loop.stop()

    assert calls >= 2


async def test_self_ping_loop_without_url_never_starts() -> None:
    loop = SelfPingLoop(health_url=None, interval_seconds=0.01)

    loop.start()

    assert loop._task is None
    await loop.stop()


@pytest.mark.parametrize("health_url", ["https://a.example.com/health"])
async def test_self_ping_loop_start_is_idempotent(health_url: str) -> None:
    loop = SelfPingLoop(
        health_url=health_url,
        interval_seconds=10,
        client=client_with(lambda request: httpx.Response(200)),
    )

    loop.start()
    first_task = loop._task
    loop.start()

    assert loop._task is first_task
    await loop.stop()
