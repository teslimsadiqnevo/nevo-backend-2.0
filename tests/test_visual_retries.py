"""A rate-limited image provider is asking us to wait, not refusing."""
import time

import httpx
import pytest

from nevo.visuals.config import VisualGenerationSettings
from nevo.visuals.service import (
    EducationalImageService,
    VisualGenerationError,
    _provider_detail,
    _retry_pause,
)


def test_a_retry_after_header_is_honoured() -> None:
    response = httpx.Response(429, headers={"retry-after": "7"})

    assert _retry_pause(response, attempt=0) == 7.0


def test_backoff_grows_when_the_provider_says_nothing() -> None:
    response = httpx.Response(429)

    pauses = [_retry_pause(response, attempt=n) for n in range(4)]

    assert pauses == sorted(pauses)
    assert pauses[0] < pauses[-1]
    assert all(pause <= 60 for pause in pauses)


def test_an_unreadable_retry_after_falls_back_to_backoff() -> None:
    response = httpx.Response(429, headers={"retry-after": "soon"})

    assert _retry_pause(response, attempt=0) > 0


def test_the_providers_own_words_are_kept() -> None:
    """A quota 429 comes back however long we wait; a busy one does not. The
    difference is in the body, and it is somebody's billing page or ours."""
    response = httpx.Response(
        429,
        json={"error": {"code": "insufficient_quota", "message": "You exceeded your quota"}},
    )

    detail = _provider_detail(response)

    assert "insufficient_quota" in detail
    assert "exceeded your quota" in detail


def test_a_body_with_no_error_object_is_not_invented() -> None:
    assert _provider_detail(httpx.Response(429, text="nope")) == ""
    assert _provider_detail(None) == ""


def service_calling(handler) -> EducationalImageService:  # type: ignore[no-untyped-def]
    service = EducationalImageService(VisualGenerationSettings(openai_api_key="key"))
    service._image_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        transport=httpx.MockTransport(handler),
        timeout=5,
    )
    return service


async def test_a_burst_of_rate_limiting_still_produces_a_picture() -> None:
    """It used to cost a lesson every one of its images."""
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"data": [{"b64_json": "aGVsbG8="}]})

    image = await service_calling(handler)._generate_image(
        "draw a bar model",
        deadline=time.monotonic() + 60,
    )

    assert image == b"hello"
    assert calls["n"] == 3


async def test_a_provider_that_keeps_refusing_says_why() -> None:
    """A quota 429 is somebody's billing page, not a backend fault."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"code": "insufficient_quota", "message": "no credit"}},
        )

    with pytest.raises(VisualGenerationError) as raised:
        await service_calling(handler)._generate_image(
            "draw a bar model",
            deadline=time.monotonic() + 5,
        )

    assert "429" in str(raised.value)
    assert "insufficient_quota" in str(raised.value)


async def test_a_refusal_that_is_not_retryable_is_not_retried() -> None:
    """A 400 is a bad prompt. Asking again changes nothing."""
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": {"code": "bad_prompt"}})

    with pytest.raises(VisualGenerationError):
        await service_calling(handler)._generate_image(
            "draw a bar model",
            deadline=time.monotonic() + 5,
        )

    assert calls["n"] == 1


async def test_retrying_stops_at_the_deadline_rather_than_running_past_it() -> None:
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"retry-after": "30"})

    with pytest.raises(VisualGenerationError):
        await service_calling(handler)._generate_image(
            "draw a bar model",
            deadline=time.monotonic() + 1,
        )

    # One call, then the pause would have overshot the deadline.
    assert calls["n"] == 1


async def test_running_out_of_credit_is_not_waited_out() -> None:
    """Out of credit arrives as a 429, same as too busy. Backing off costs
    every image in a lesson half a minute for an answer that cannot change."""
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            429,
            json={
                "error": {
                    "code": "credit_balance_exhausted",
                    "message": "You have no credits remaining.",
                }
            },
        )

    with pytest.raises(VisualGenerationError) as raised:
        await service_calling(handler)._generate_image(
            "draw a bar model",
            deadline=time.monotonic() + 120,
        )

    assert calls["n"] == 1
    assert "credit_balance_exhausted" in str(raised.value)


async def test_a_busy_provider_is_still_waited_out() -> None:
    """The fast path for quota must not swallow ordinary rate limiting."""
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"data": [{"b64_json": "aGVsbG8="}]})

    image = await service_calling(handler)._generate_image(
        "draw a bar model",
        deadline=time.monotonic() + 60,
    )

    assert image == b"hello"
    assert calls["n"] == 2
