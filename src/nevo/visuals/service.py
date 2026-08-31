import base64
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from nevo.ai_gateway.privacy import AiPrivacyGuard
from nevo.storage import StorageError, SupabaseStorage
from nevo.visuals.config import VisualGenerationSettings

MAX_VALIDATION_IMAGE_BYTES = 5_000_000
"""Anthropic rejects a base64 image source larger than 5MB."""

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "issues": {"type": "string"},
    },
    "required": ["approved", "issues"],
    "additionalProperties": False,
}


class VisualGenerationError(RuntimeError):
    pass


class EducationalImageService:
    """Generates a lesson visual and refuses to ship one that teaches the wrong thing.

    A dedicated image model draws the candidate; Claude vision then reviews it
    against the lesson text. A rejected image is regenerated with the reviewer's
    correction appended, up to ``max_attempts`` times.
    """

    def __init__(self, settings: VisualGenerationSettings) -> None:
        self._settings = settings
        self._privacy = AiPrivacyGuard()
        key = settings.supabase_service_role_key
        self._storage = SupabaseStorage(
            base_url=str(settings.supabase_url) if settings.supabase_url else None,
            service_role_key=key.get_secret_value() if key else None,
            bucket=settings.storage_bucket,
            public=settings.storage_public,
            signed_url_ttl_seconds=settings.signed_url_ttl_seconds,
        )

    @property
    def configured(self) -> bool:
        return bool(
            self._settings.openai_api_key
            and self._settings.anthropic_api_key
            and self._storage.configured
        )

    async def generate(
        self,
        *,
        title: str | None,
        lesson_text: str,
        requested_prompt: str | None,
    ) -> dict[str, object]:
        if not self.configured:
            raise VisualGenerationError(
                "Image generation, review, or storage is not configured"
            )
        safe_text = self._privacy.sanitize_text(lesson_text, pseudonym="the learner")[:4_000]
        prompt = self._prompt(title, safe_text, requested_prompt)
        digest = hashlib.sha256(
            f"{self._settings.image_model}\0{prompt}".encode()
        ).hexdigest()
        object_path = f"images/lessons/{digest}.png"
        attempts = 0
        try:
            if not await self._storage.exists(object_path):
                accepted, attempts = await self._draw_until_approved(prompt, safe_text)
                await self._storage.upload(object_path, accepted, content_type="image/png")
            image_url = await self._storage.url_for(object_path)
        except StorageError as error:
            raise VisualGenerationError(str(error)) from error
        return {
            "type": "ai_generated_image",
            "imageUrl": image_url,
            "storagePath": object_path,
            "prompt": prompt,
            "provider": self._settings.image_model,
            "reviewedBy": self._settings.validator_model,
            "reviewAttempts": attempts,
            "generatedAt": datetime.now(UTC).isoformat(),
            "caption": title or "Lesson visual",
            "qualityValidated": True,
            "urlExpiresInSeconds": (
                None if self._storage.public else self._storage.signed_url_ttl_seconds
            ),
        }

    async def _draw_until_approved(self, prompt: str, lesson_text: str) -> tuple[bytes, int]:
        issues = ""
        for attempt in range(1, self._settings.max_attempts + 1):
            correction = f"\n\nCorrect these problems from the previous attempt: {issues}"
            image = await self._generate_image(prompt + (correction if issues else ""))
            approved, issues = await self._review_image(image=image, lesson_text=lesson_text)
            if approved:
                return image, attempt
        raise VisualGenerationError(
            f"Generated image failed educational review: {issues[:300]}"
        )

    def _prompt(self, title: str | None, text: str, requested: str | None) -> str:
        return (
            "Create a precise educational visual for a school lesson. The image must teach the "
            "concept accurately, be age-appropriate, uncluttered, culturally inclusive, and easy "
            "to understand on a tablet. Prefer a clear diagram, process illustration, number "
            "representation, or labelled instructional scene over decorative art. Preserve every "
            "mathematical quantity and scientific relationship exactly. Do not invent facts. Avoid "
            "logos, watermarks, diagnostic language, student names, tiny text, long paragraphs. "
            f"Lesson title: {title or 'Untitled'}. Lesson content: {text}. "
            f"Teacher visual direction: {requested or 'Choose the clearest instructional visual.'}"
        )

    async def _generate_image(self, prompt: str) -> bytes:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{str(self._settings.openai_base_url).rstrip('/')}/images/generations",
                headers={"Authorization": f"Bearer {self._openai_key()}"},
                json={
                    "model": self._settings.image_model,
                    "prompt": prompt,
                    "quality": self._settings.image_quality,
                    "size": self._settings.image_size,
                    "output_format": "png",
                },
            )
        if response.is_error:
            raise VisualGenerationError(
                f"Image provider failed with status {response.status_code}"
            )
        try:
            encoded = response.json()["data"][0]["b64_json"]
            return base64.b64decode(encoded, validate=True)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise VisualGenerationError("Image provider returned no valid PNG") from error

    async def _review_image(self, *, image: bytes, lesson_text: str) -> tuple[bool, str]:
        encoded = base64.b64encode(image).decode()
        if len(encoded) > MAX_VALIDATION_IMAGE_BYTES:
            raise VisualGenerationError(
                "Generated image is too large to review; lower IMAGE_GENERATION_SIZE"
            )
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{str(self._settings.anthropic_base_url).rstrip('/')}/messages",
                headers={
                    "x-api-key": self._anthropic_key(),
                    "anthropic-version": self._settings.anthropic_version,
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._settings.validator_model,
                    "max_tokens": 1_024,
                    "system": (
                        "You review images used to teach children. Approve an image only if it is "
                        "factually correct, numerically exact, clearly readable, relevant to the "
                        "lesson, and age-appropriate. Reject anything misleading, mislabelled, "
                        "cluttered, or decorative rather than instructional. When rejecting, state "
                        "the specific correction the illustrator must make."
                    ),
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": encoded,
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": (
                                        "Review this image against the lesson content below.\n\n"
                                        f"Lesson content: {lesson_text}"
                                    ),
                                },
                            ],
                        }
                    ],
                    "output_config": {
                        "format": {"type": "json_schema", "schema": REVIEW_SCHEMA}
                    },
                },
            )
        if response.is_error:
            raise VisualGenerationError(
                f"Image review failed with status {response.status_code}"
            )
        return self._parse_review(response.json())

    @staticmethod
    def _parse_review(body: Any) -> tuple[bool, str]:
        try:
            text = next(
                block["text"]
                for block in body["content"]
                if block.get("type") == "text" and block.get("text")
            )
            payload = json.loads(text)
            return bool(payload["approved"]), str(payload.get("issues") or "")
        except (
            KeyError,
            StopIteration,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise VisualGenerationError("Image reviewer returned malformed output") from error

    def _openai_key(self) -> str:
        key = self._settings.openai_api_key
        if key is None:
            raise VisualGenerationError("Image generation is not configured")
        return key.get_secret_value()

    def _anthropic_key(self) -> str:
        key = self._settings.anthropic_api_key
        if key is None:
            raise VisualGenerationError("Image review is not configured")
        return key.get_secret_value()
