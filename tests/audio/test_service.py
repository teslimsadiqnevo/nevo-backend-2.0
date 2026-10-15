from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from nevo.audio.config import AudioSettings
from nevo.audio.service import AudioGenerationError, AudioGenerationService


@pytest.mark.asyncio
async def test_generates_and_uploads_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "HEAD":
            return httpx.Response(404)
        if request.url.host == "api.yarngpt.ai":
            assert request.headers["Authorization"] == "Bearer yarn-secret"
            return httpx.Response(200, content=b"mp3-bytes")
        assert request.headers["Authorization"] == "Bearer supabase-secret"
        assert request.headers["x-upsert"] == "true"
        assert request.content == b"mp3-bytes"
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    service = AudioGenerationService(_settings())

    result = await service.generate("  Explain   equivalent fractions. ")

    assert result["provider"] == "yarngpt"
    assert result["audioUrl"].startswith(
        "https://project.supabase.co/storage/v1/object/public/lesson-media/"
    )
    assert [request.method for request in requests] == ["HEAD", "POST", "POST"]


@pytest.mark.asyncio
async def test_reuses_existing_supabase_object(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)

    result = await AudioGenerationService(_settings()).generate("Cached audio")

    assert result["provider"] == "yarngpt"
    assert len(requests) == 1
    assert requests[0].method == "HEAD"


def _install(monkeypatch: pytest.MonkeyPatch, handler) -> None:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def client(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)


@pytest.mark.asyncio
async def test_a_slow_reply_is_tried_again(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"yarngpt": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(404)
        if request.url.host == "api.yarngpt.ai":
            calls["yarngpt"] += 1
            if calls["yarngpt"] == 1:
                raise httpx.ReadTimeout("slow", request=request)
            return httpx.Response(200, content=b"mp3-bytes")
        return httpx.Response(200)

    _install(monkeypatch, handler)

    result = await AudioGenerationService(_settings()).generate("Explain fractions.")

    assert result["provider"] == "yarngpt"
    assert calls["yarngpt"] == 2


@pytest.mark.asyncio
async def test_a_provider_that_never_answers_fails_the_segment_not_the_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parse catches AudioGenerationError and flags the segment.

    A raw httpx.ReadTimeout went past that and failed the whole lesson.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(404)
        raise httpx.ReadTimeout("slow", request=request)

    _install(monkeypatch, handler)

    with pytest.raises(AudioGenerationError, match="ReadTimeout"):
        await AudioGenerationService(_settings()).generate("Explain fractions.")


def _settings() -> AudioSettings:
    return AudioSettings(
        YARNGPT_API_KEY=SecretStr("yarn-secret"),
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_SERVICE_ROLE_KEY=SecretStr("supabase-secret"),
        SUPABASE_STORAGE_BUCKET="lesson-media",
        SUPABASE_STORAGE_PUBLIC=True,
    )


@pytest.mark.asyncio
async def test_rate_limit_honours_retry_after_and_reuses_idempotency(monkeypatch):
    requests = []
    sleep = AsyncMock()
    monkeypatch.setattr("nevo.audio.service.asyncio.sleep", sleep)

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, content=b"mp3")

    _install(monkeypatch, handler)
    result = await AudioGenerationService(_settings())._generate_audio("A short lesson.")
    assert result == b"mp3"
    sleep.assert_awaited_once_with(3.0)
    assert requests[0].headers["Idempotency-Key"] == requests[1].headers["Idempotency-Key"]


@pytest.mark.asyncio
async def test_daily_limit_fails_fast_and_is_shared_across_instances(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "8000"})

    _install(monkeypatch, handler)
    for _ in range(2):
        with pytest.raises(AudioGenerationError, match="rate limited"):
            await AudioGenerationService(_settings())._generate_audio("Read this.")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_current_tts_job_is_polled_and_only_audio_is_returned(monkeypatch):
    import json

    monkeypatch.setattr("nevo.audio.service.asyncio.sleep", AsyncMock())

    def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["output_format"] == "mp3"
            assert "response_format" not in body
            return httpx.Response(202, json={"job_id": "job-123", "status": "queued"})
        if request.url.path == "/api/v1/status/job-123":
            return httpx.Response(
                200, json={"status": "completed", "audio_url": "https://media.example/audio.mp3"}
            )
        assert "Authorization" not in request.headers
        return httpx.Response(200, content=b"generated-mp3", headers={"Content-Type": "audio/mpeg"})

    _install(monkeypatch, handler)
    result = await AudioGenerationService(_settings())._generate_audio("Read this.")
    assert result == b"generated-mp3"
