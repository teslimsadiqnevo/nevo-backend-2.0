"""Educational image generation and review tests."""

import base64
import io
import json

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr

from nevo.visuals import EducationalImageService, VisualGenerationError, VisualGenerationSettings


def _png(width: int = 1536, height: int = 1024) -> bytes:
    """A real PNG: the service decodes what the provider sends now."""
    raw = io.BytesIO()
    Image.new("RGB", (width, height), (12, 42, 110)).save(raw, format="PNG")
    return raw.getvalue()


PNG = _png()
ENCODED_PNG = base64.b64encode(PNG).decode()


def _settings(**overrides: object) -> VisualGenerationSettings:
    values: dict[str, object] = {
        "OPENAI_API_KEY": SecretStr("openai-secret"),
        "AI_ANTHROPIC_API_KEY": SecretStr("anthropic-secret"),
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": SecretStr("supabase-secret"),
        "SUPABASE_STORAGE_BUCKET": "lesson-media",
        "SUPABASE_STORAGE_PUBLIC": True,
    }
    values.update(overrides)
    return VisualGenerationSettings(**values)  # type: ignore[arg-type]


def _review(approved: bool, issues: str = "") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "content": [
                {"type": "text", "text": json.dumps({"approved": approved, "issues": issues})}
            ]
        },
    )


class _Fake:
    """Routes each provider call and records what was asked for."""

    def __init__(self, reviews: list[httpx.Response], *, object_exists: bool = False) -> None:
        self.reviews = reviews
        self.object_exists = object_exists
        self.image_prompts: list[str] = []
        self.uploads: list[bytes] = []
        self.review_images: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "HEAD":
            return httpx.Response(200 if self.object_exists else 404)
        if "openai.com" in url:
            self.image_prompts.append(json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"data": [{"b64_json": ENCODED_PNG}]})
        if "api.anthropic.com" in url:
            assert request.headers["x-api-key"] == "anthropic-secret"
            body = json.loads(request.content)
            self.review_images.append(body["messages"][0]["content"][0]["source"]["data"])
            return self.reviews.pop(0)
        self.uploads.append(request.content)
        return httpx.Response(200)


def _install(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def client(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)


def test_service_is_unconfigured_without_keys() -> None:
    assert not EducationalImageService(VisualGenerationSettings()).configured
    assert not EducationalImageService(_settings(OPENAI_API_KEY=None)).configured
    assert not EducationalImageService(_settings(AI_ANTHROPIC_API_KEY=None)).configured
    assert EducationalImageService(_settings()).configured


async def test_unconfigured_service_refuses_to_generate() -> None:
    service = EducationalImageService(VisualGenerationSettings())

    with pytest.raises(VisualGenerationError, match="not configured"):
        await service.generate(title="T", lesson_text="body", requested_prompt=None)


async def test_approved_image_is_uploaded_and_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _Fake([_review(True)])
    _install(monkeypatch, fake)

    result = await EducationalImageService(_settings()).generate(
        title="Equivalent fractions",
        lesson_text="One half equals two quarters.",
        requested_prompt="Show a fraction bar",
    )

    assert result["type"] == "ai_generated_image"
    assert result["provider"] == "gpt-image-2"
    assert result["reviewedBy"] == "claude-opus-4-8"
    assert result["reviewAttempts"] == 1
    assert result["qualityValidated"] is True
    assert str(result["imageUrl"]).startswith(
        "https://project.supabase.co/storage/v1/object/public/lesson-media/images/lessons/"
    )
    # Two objects: the display image and its preview, both WebP.
    assert len(fake.uploads) == 2
    assert all(item[:4] == b"RIFF" for item in fake.uploads)
    assert fake.review_images == [ENCODED_PNG]
    assert "Show a fraction bar" in fake.image_prompts[0]


async def test_rejected_image_is_regenerated_with_the_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _Fake([_review(False, "The denominator is wrong"), _review(True)])
    _install(monkeypatch, fake)

    result = await EducationalImageService(_settings()).generate(
        title="Fractions",
        lesson_text="One half equals two quarters.",
        requested_prompt=None,
    )

    assert result["reviewAttempts"] == 2
    assert len(fake.image_prompts) == 2
    assert "The denominator is wrong" in fake.image_prompts[1]
    assert len(fake.uploads) == 2


async def test_persistently_rejected_image_is_never_uploaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _Fake([_review(False, "Still wrong") for _ in range(3)])
    _install(monkeypatch, fake)

    with pytest.raises(VisualGenerationError, match="Still wrong"):
        await EducationalImageService(_settings()).generate(
            title="Fractions",
            lesson_text="One half equals two quarters.",
            requested_prompt=None,
        )

    assert fake.uploads == []


async def test_existing_object_skips_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Fake([], object_exists=True)
    _install(monkeypatch, fake)

    result = await EducationalImageService(_settings()).generate(
        title="Fractions",
        lesson_text="One half equals two quarters.",
        requested_prompt=None,
    )

    assert fake.image_prompts == []
    assert fake.uploads == []
    assert result["reviewAttempts"] == 0


async def test_private_bucket_returns_a_signed_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/object/sign/" in str(request.url):
            return httpx.Response(200, json={"signedURL": "/object/sign/x?token=t"})
        return _Fake([_review(True)], object_exists=True)(request)

    _install(monkeypatch, handler)

    result = await EducationalImageService(_settings(SUPABASE_STORAGE_PUBLIC=False)).generate(
        title="Fractions", lesson_text="Half.", requested_prompt=None
    )

    assert result["imageUrl"] == "https://project.supabase.co/storage/v1/object/sign/x?token=t"
    assert result["urlExpiresInSeconds"] == 604_800


async def test_lesson_text_is_redacted_before_leaving_the_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _Fake([_review(True)])
    _install(monkeypatch, fake)

    await EducationalImageService(_settings()).generate(
        title="Fractions",
        lesson_text="Student name: Ada Lovelace. Email: ada@example.com. Half of eight is four.",
        requested_prompt=None,
    )

    prompt = fake.image_prompts[0]
    assert "ada@example.com" not in prompt
    assert "Ada Lovelace" not in prompt
    assert "Half of eight is four." in prompt


async def test_image_provider_failure_is_surfaced(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(404)
        return httpx.Response(429)

    _install(monkeypatch, handler)

    with pytest.raises(VisualGenerationError, match="429"):
        await EducationalImageService(_settings()).generate(
            title="T", lesson_text="body", requested_prompt=None
        )


async def test_malformed_review_output_is_surfaced(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Fake([httpx.Response(200, json={"content": [{"type": "text", "text": "not json"}]})])
    _install(monkeypatch, fake)

    with pytest.raises(VisualGenerationError, match="malformed"):
        await EducationalImageService(_settings()).generate(
            title="T", lesson_text="body", requested_prompt=None
        )


async def test_a_refused_review_says_what_the_provider_said(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A status code on its own is not a reason anybody can act on.

    Every picture in three lessons was lost to "Image review failed with
    status 400" - a note that named the code and nothing else, so there was
    no way to tell a rejected prompt from a retired model from a malformed
    request without redeploying to find out.
    """

    fake = _Fake(
        [
            httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "model: claude-opus-4-8 is not available",
                    },
                },
            )
        ]
    )
    _install(monkeypatch, fake)

    with pytest.raises(VisualGenerationError) as raised:
        await EducationalImageService(_settings()).generate(
            title="T", lesson_text="body", requested_prompt=None
        )

    assert "400" in str(raised.value)
    assert "not available" in str(raised.value)
