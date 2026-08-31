import hashlib

import httpx

from nevo.audio.config import AudioSettings
from nevo.storage import StorageError, SupabaseStorage


class AudioGenerationError(RuntimeError):
    pass


class AudioGenerationService:
    def __init__(self, settings: AudioSettings) -> None:
        self._settings = settings
        key = settings.supabase_service_role_key
        self._storage = SupabaseStorage(
            base_url=str(settings.supabase_url) if settings.supabase_url else None,
            service_role_key=key.get_secret_value() if key else None,
            bucket=settings.supabase_storage_bucket,
            public=settings.supabase_storage_public,
            signed_url_ttl_seconds=settings.supabase_signed_url_ttl_seconds,
        )

    @property
    def configured(self) -> bool:
        return bool(self._settings.yarngpt_api_key and self._storage.configured)

    async def generate(self, script: str) -> dict[str, object]:
        normalized = " ".join(script.split()).strip()[:2_000]
        if not normalized:
            raise AudioGenerationError("Audio script is empty")
        if not self.configured:
            raise AudioGenerationError("YarnGPT or Supabase Storage is not configured")
        digest = hashlib.sha256(
            f"{self._settings.yarngpt_voice}\0{normalized}".encode()
        ).hexdigest()
        object_path = f"audio/yarngpt/{digest}.mp3"
        try:
            if not await self._storage.exists(object_path):
                audio = await self._generate_audio(normalized)
                await self._storage.upload(object_path, audio, content_type="audio/mpeg")
            audio_url = await self._storage.url_for(object_path)
        except StorageError as error:
            raise AudioGenerationError(str(error)) from error
        return {
            "script": normalized,
            "audioUrl": audio_url,
            "storagePath": object_path,
            "durationMs": 0,
            "provider": "yarngpt",
            "voice": self._settings.yarngpt_voice,
            "format": "mp3",
            "requiresAuthentication": False,
            "urlExpiresInSeconds": (
                None if self._storage.public else self._storage.signed_url_ttl_seconds
            ),
        }

    async def _generate_audio(self, text: str) -> bytes:
        api_key = self._settings.yarngpt_api_key
        if api_key is None:
            raise AudioGenerationError("YarnGPT is not configured")
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                str(self._settings.yarngpt_api_url),
                headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
                json={
                    "text": text,
                    "voice": self._settings.yarngpt_voice,
                    "response_format": "mp3",
                },
            )
        if response.is_error or not response.content:
            raise AudioGenerationError(
                f"YarnGPT generation failed with status {response.status_code}"
            )
        return response.content
