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
        if request.url.host == "yarngpt.ai":
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
        if request.url.host == "yarngpt.ai":
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
