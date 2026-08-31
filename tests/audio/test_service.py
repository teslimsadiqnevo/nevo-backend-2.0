import httpx
import pytest
from pydantic import SecretStr

from nevo.audio.config import AudioSettings
from nevo.audio.service import AudioGenerationService


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


def _settings() -> AudioSettings:
    return AudioSettings(
        YARNGPT_API_KEY=SecretStr("yarn-secret"),
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_SERVICE_ROLE_KEY=SecretStr("supabase-secret"),
        SUPABASE_STORAGE_BUCKET="lesson-media",
        SUPABASE_STORAGE_PUBLIC=True,
    )
