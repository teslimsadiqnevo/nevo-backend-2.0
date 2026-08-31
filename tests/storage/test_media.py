"""Lesson media URL re-issue tests."""
import httpx
import pytest

from nevo.storage import InvalidMediaPathError, LessonMediaService, SupabaseStorage


def _service(*, public: bool) -> LessonMediaService:
    return LessonMediaService(
        SupabaseStorage(
            base_url="https://project.supabase.co",
            service_role_key="supabase-secret",
            bucket="lesson-media",
            public=public,
            signed_url_ttl_seconds=3_600,
        )
    )


async def test_public_bucket_url_never_expires() -> None:
    url, expires_in = await _service(public=True).url_for("audio/yarngpt/abc.mp3")

    assert url.endswith("/public/lesson-media/audio/yarngpt/abc.mp3")
    assert expires_in is None


async def test_private_bucket_url_reports_its_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"signedURL": "/object/sign/x?token=t"})
    )
    original_client = httpx.AsyncClient

    def client(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)

    url, expires_in = await _service(public=False).url_for("images/lessons/abc.png")

    assert url == "https://project.supabase.co/storage/v1/object/sign/x?token=t"
    assert expires_in == 3_600


@pytest.mark.parametrize(
    "path",
    [
        "secrets/service-account.json",
        "audio/../../etc/passwd",
        "",
        "   ",
        "/",
    ],
)
async def test_paths_outside_lesson_media_are_rejected(path: str) -> None:
    with pytest.raises(InvalidMediaPathError):
        await _service(public=True).url_for(path)


async def test_leading_slash_is_tolerated() -> None:
    url, _ = await _service(public=True).url_for("/audio/yarngpt/abc.mp3")

    assert url.endswith("/lesson-media/audio/yarngpt/abc.mp3")
