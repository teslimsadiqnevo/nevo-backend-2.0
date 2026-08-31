"""Supabase object storage tests."""
import httpx
import pytest

from nevo.storage import MAX_SIGNED_URL_TTL_SECONDS, StorageError, SupabaseStorage


def _mock_httpx(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(recording)
    original_client = httpx.AsyncClient

    def client(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return requests


def _storage(*, public: bool = True, ttl: int = 3_600) -> SupabaseStorage:
    return SupabaseStorage(
        base_url="https://project.supabase.co",
        service_role_key="supabase-secret",
        bucket="lesson-media",
        public=public,
        signed_url_ttl_seconds=ttl,
    )


def test_storage_is_unconfigured_without_url_or_key() -> None:
    assert not SupabaseStorage(
        base_url=None,
        service_role_key="secret",
        bucket="lesson-media",
        public=True,
    ).configured
    assert not SupabaseStorage(
        base_url="https://project.supabase.co",
        service_role_key=None,
        bucket="lesson-media",
        public=True,
    ).configured
    assert _storage().configured


async def test_public_bucket_returns_a_direct_public_url() -> None:
    url = await _storage(public=True).url_for("audio/yarngpt/abc.mp3")

    assert url == (
        "https://project.supabase.co/storage/v1/object/public/"
        "lesson-media/audio/yarngpt/abc.mp3"
    )


async def test_private_bucket_returns_a_signed_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "/storage/v1/object/sign/lesson-media/audio/yarngpt/abc.mp3" in str(request.url)
        assert b'"expiresIn":3600' in request.content.replace(b" ", b"")
        return httpx.Response(
            200,
            json={
                "signedURL": "/object/sign/lesson-media/audio/yarngpt/abc.mp3?token=jwt-token"
            },
        )

    requests = _mock_httpx(monkeypatch, handler)

    url = await _storage(public=False).url_for("audio/yarngpt/abc.mp3")

    assert url == (
        "https://project.supabase.co/storage/v1/object/sign/"
        "lesson-media/audio/yarngpt/abc.mp3?token=jwt-token"
    )
    assert len(requests) == 1
    assert requests[0].headers["apikey"] == "supabase-secret"


async def test_signed_url_accepts_an_absolute_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_httpx(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"signedURL": "https://cdn.supabase.co/signed/abc?token=jwt"}
        ),
    )

    url = await _storage(public=False).signed_url("audio/abc.mp3")

    assert url == "https://cdn.supabase.co/signed/abc?token=jwt"


async def test_signed_url_ttl_is_clamped_to_the_supabase_maximum() -> None:
    storage = _storage(public=False, ttl=MAX_SIGNED_URL_TTL_SECONDS * 10)

    assert storage.signed_url_ttl_seconds == MAX_SIGNED_URL_TTL_SECONDS


async def test_signed_url_raises_when_supabase_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_httpx(monkeypatch, lambda request: httpx.Response(403))

    with pytest.raises(StorageError, match="403"):
        await _storage(public=False).signed_url("audio/abc.mp3")


async def test_signed_url_raises_on_a_malformed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_httpx(monkeypatch, lambda request: httpx.Response(200, json={"error": "nope"}))

    with pytest.raises(StorageError, match="no signed URL"):
        await _storage(public=False).signed_url("audio/abc.mp3")


async def test_upload_upserts_with_the_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = _mock_httpx(monkeypatch, lambda request: httpx.Response(200))

    await _storage().upload("images/a.png", b"png-bytes", content_type="image/png")

    assert requests[0].headers["x-upsert"] == "true"
    assert requests[0].headers["Content-Type"] == "image/png"
    assert requests[0].content == b"png-bytes"


async def test_upload_raises_when_supabase_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_httpx(monkeypatch, lambda request: httpx.Response(413))

    with pytest.raises(StorageError, match="413"):
        await _storage().upload("images/a.png", b"png", content_type="image/png")


async def test_exists_is_true_when_head_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_httpx(monkeypatch, lambda request: httpx.Response(200))

    assert await _storage().exists("images/a.png")


async def test_exists_is_false_when_head_misses(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_httpx(monkeypatch, lambda request: httpx.Response(404))

    assert not await _storage().exists("images/a.png")
