import hashlib
from urllib.parse import quote

import httpx

from nevo.audio.config import AudioSettings


class AudioGenerationError(RuntimeError):
    pass


class AudioGenerationService:
    def __init__(self, settings: AudioSettings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        return bool(
            self._settings.yarngpt_api_key
            and self._settings.supabase_url
            and self._settings.supabase_service_role_key
        )

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
        if not await self._object_exists(object_path):
            audio = await self._generate_audio(normalized)
            await self._upload(object_path, audio)
        return {
            "script": normalized,
            "audioUrl": self._object_url(object_path),
            "storagePath": object_path,
            "durationMs": 0,
            "provider": "yarngpt",
            "voice": self._settings.yarngpt_voice,
            "format": "mp3",
            "requiresAuthentication": not self._settings.supabase_storage_public,
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

    async def _object_exists(self, object_path: str) -> bool:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.head(
                self._storage_object_url(object_path),
                headers=self._storage_headers(),
            )
        return response.is_success

    async def _upload(self, object_path: str, content: bytes) -> None:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self._storage_object_url(object_path),
                headers={
                    **self._storage_headers(),
                    "Content-Type": "audio/mpeg",
                    "x-upsert": "true",
                },
                content=content,
            )
        if response.is_error:
            raise AudioGenerationError(
                f"Supabase audio upload failed with status {response.status_code}"
            )

    def _storage_headers(self) -> dict[str, str]:
        key = self._settings.supabase_service_role_key
        if key is None:
            raise AudioGenerationError("Supabase Storage is not configured")
        value = key.get_secret_value()
        return {"apikey": value, "Authorization": f"Bearer {value}"}

    def _storage_object_url(self, object_path: str) -> str:
        base = str(self._settings.supabase_url).rstrip("/")
        bucket = quote(self._settings.supabase_storage_bucket, safe="")
        path = quote(object_path, safe="/")
        return f"{base}/storage/v1/object/{bucket}/{path}"

    def _object_url(self, object_path: str) -> str:
        base = str(self._settings.supabase_url).rstrip("/")
        bucket = quote(self._settings.supabase_storage_bucket, safe="")
        path = quote(object_path, safe="/")
        visibility = "public/" if self._settings.supabase_storage_public else ""
        return f"{base}/storage/v1/object/{visibility}{bucket}/{path}"
