import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

import httpx

from nevo.audio.config import AudioSettings
from nevo.storage import StorageError, SupabaseStorage

#: Two thousand characters of speech takes YarnGPT longer than a minute on a
#: busy day. At sixty seconds one slow segment timed out mid-upload.
YARNGPT_TIMEOUT_SECONDS = 120.0

#: A dropped connection or a slow reply is usually gone on the next try.
YARNGPT_ATTEMPTS = 3
MAX_RATE_LIMIT_WAIT = 30.0
JOB_TIMEOUT_SECONDS = 300.0


@dataclass
class _AccountGate:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    retry_at: float = 0.0
    voice_names: tuple[str, ...] = ()
    default_voice: str | None = None
    catalogue_updated_at: float = 0.0
    quota_retry_at: float = 0.0
    quota_error: str | None = None


# Share the account's queue across concurrent uploads/service instances in
# this worker; never bind an asyncio lock to another event loop.
_GATES: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, _AccountGate]] = WeakKeyDictionary()


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
        except httpx.HTTPError as error:
            # A network failure is this segment's audio failing, not the
            # lesson's. Uncaught, a single read timeout here failed the whole
            # parse and the teacher lost every segment that had worked.
            raise AudioGenerationError(
                f"Audio request failed: {error.__class__.__name__}"
            ) from error
        return {
            "script": normalized,
            "audioUrl": audio_url,
            "storagePath": object_path,
            "durationMs": None,
            "provider": "yarngpt",
            # The provider may select its default if a configured voice was
            # retired; do not claim the requested voice is the delivered one.
            "voice": None,
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
        fingerprint = hashlib.sha256(api_key.get_secret_value().encode()).hexdigest()
        gates = _GATES.setdefault(asyncio.get_running_loop(), {})
        gate = gates.setdefault(fingerprint, _AccountGate())
        async with gate.lock:
            if gate.quota_error and time.monotonic() < gate.quota_retry_at:
                raise AudioGenerationError(
                    f"YarnGPT requests paused after {gate.quota_error}; "
                    "credit/account action required"
                )
            wait = gate.retry_at - time.monotonic()
            if wait > MAX_RATE_LIMIT_WAIT:
                raise AudioGenerationError(
                    f"YarnGPT rate limited; retry after {round(wait)} seconds"
                )
            if wait > 0:
                await asyncio.sleep(wait)
            async with httpx.AsyncClient(timeout=YARNGPT_TIMEOUT_SECONDS) as client:
                url = str(self._settings.yarngpt_api_url)
                auth = {"Authorization": f"Bearer {api_key.get_secret_value()}"}
                voice = await self._resolve_voice(
                    client, url, gate, auth, requested=self._settings.yarngpt_voice
                )
                body: dict[str, str] = {"text": text, "output_format": "mp3", "voice": voice}
                digest = hashlib.sha256(f"{voice}\0{text}".encode()).hexdigest()
                headers = {
                    "Authorization": f"Bearer {api_key.get_secret_value()}",
                    "Idempotency-Key": digest,
                }
                response = await self._request(
                    client, "POST", url, gate, headers=headers, json=body
                )
                if "application/json" not in response.headers.get("content-type", ""):
                    return self._audio_bytes(response)
                try:
                    job_id = str(response.json()["job_id"])
                except (ValueError, KeyError, TypeError) as error:
                    raise AudioGenerationError("YarnGPT returned no synthesis job") from error
                if not job_id or not all(
                    char.isascii() and (char.isalnum() or char in "-_") for char in job_id
                ):
                    raise AudioGenerationError("YarnGPT returned an invalid synthesis job")
                status_url = url.rsplit("/", 1)[0] + f"/status/{job_id}"
                deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
                poll_delay = 1.0
                while time.monotonic() < deadline:
                    await asyncio.sleep(poll_delay)
                    response = await self._request(
                        client,
                        "GET",
                        status_url,
                        gate,
                        headers={"Authorization": headers["Authorization"]},
                    )
                    try:
                        state = response.json()
                    except ValueError as error:
                        raise AudioGenerationError(
                            "YarnGPT returned an invalid job status"
                        ) from error
                    if not isinstance(state, dict):
                        raise AudioGenerationError("YarnGPT returned an invalid job status")
                    if state.get("status") == "failed":
                        raise AudioGenerationError("YarnGPT synthesis job failed")
                    if state.get("status") == "completed":
                        audio_url = state.get("audio_url")
                        if not isinstance(audio_url, str) or not audio_url.startswith("https://"):
                            raise AudioGenerationError("YarnGPT returned no secure audio URL")
                        # Signed media URLs need no account credential.
                        audio = await client.get(audio_url, follow_redirects=True)
                        return self._audio_bytes(audio)
                    poll_delay = min(5.0, poll_delay + 1.0)
                raise AudioGenerationError("YarnGPT synthesis job timed out")

    async def _resolve_voice(
        self,
        client: httpx.AsyncClient,
        url: str,
        gate: _AccountGate,
        headers: dict[str, str],
        *,
        requested: str | None,
        refresh: bool = False,
    ) -> str:
        if refresh or not gate.voice_names or time.monotonic() - gate.catalogue_updated_at > 900:
            response = await self._request(
                client, "GET", url.rsplit("/", 1)[0] + "/voices", gate, headers=headers
            )
            try:
                payload = response.json()
                entries = payload if isinstance(payload, list) else payload.get("voices", [])
            except (ValueError, AttributeError) as error:
                raise AudioGenerationError("YarnGPT returned an invalid voice catalogue") from error
            if not isinstance(entries, list):
                raise AudioGenerationError("YarnGPT returned an invalid voice catalogue")
            names = [
                entry
                for entry in entries
                if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"]
            ]
            gate.voice_names = tuple(entry["name"] for entry in names)
            gate.default_voice = next(
                (entry["name"] for entry in names if entry.get("default") is True), None
            )
            gate.catalogue_updated_at = time.monotonic()
        if requested:
            for name in gate.voice_names:
                if name.casefold() == requested.strip().casefold():
                    return name
        if gate.default_voice:
            return gate.default_voice
        raise AudioGenerationError("YarnGPT has no default voice; configure a current voice ID")

    async def _request(
        self, client: httpx.AsyncClient, method: str, url: str, gate: _AccountGate, **kwargs
    ) -> httpx.Response:
        for attempt in range(YARNGPT_ATTEMPTS):
            try:
                response = await client.request(method, url, **kwargs)
            except httpx.TransportError:
                if attempt == YARNGPT_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code == 429:
                pause = _retry_after(response, attempt)
                gate.retry_at = time.monotonic() + pause
                if pause > MAX_RATE_LIMIT_WAIT or attempt == YARNGPT_ATTEMPTS - 1:
                    raise AudioGenerationError(
                        f"YarnGPT rate limited; retry after {round(pause)} seconds"
                    )
                await asyncio.sleep(pause)
                continue
            if response.status_code in {500, 502, 503, 504} and attempt < YARNGPT_ATTEMPTS - 1:
                await asyncio.sleep(2**attempt)
                continue
            if response.is_error:
                try:
                    provider_error = response.json().get("error", {})
                except (ValueError, AttributeError):
                    provider_error = {}
                if not isinstance(provider_error, dict):
                    provider_error = {}
                code = str(provider_error.get("code") or "UNKNOWN")[:80]
                if response.status_code == 402:
                    gate.quota_error = code
                    gate.quota_retry_at = time.monotonic() + 300
                body = kwargs.get("json")
                if (
                    response.status_code == 404
                    and code == "VOICE_NOT_FOUND"
                    and method == "POST"
                    and isinstance(body, dict)
                    and body.get("voice")
                    and attempt < YARNGPT_ATTEMPTS - 1
                ):
                    auth = {"Authorization": kwargs["headers"]["Authorization"]}
                    voice = await self._resolve_voice(
                        client, url, gate, auth, requested=None, refresh=True
                    )
                    body = {**body, "voice": voice}
                    kwargs["json"] = body
                    headers = dict(kwargs.get("headers", {}))
                    headers["Idempotency-Key"] = hashlib.sha256(
                        (voice + "\0" + str(body["text"])).encode()
                    ).hexdigest()
                    kwargs["headers"] = headers
                    continue
                trace = str(
                    provider_error.get("trace_id")
                    or response.headers.get("X-Request-Id", "unknown")
                )[:100]
                raise AudioGenerationError(
                    f"YarnGPT {method} {httpx.URL(url).path} failed with status "
                    f"{response.status_code} ({code}, trace {trace})"
                )
            return response
        raise AudioGenerationError("YarnGPT retry limit reached")

    @staticmethod
    def _audio_bytes(response: httpx.Response) -> bytes:
        if (
            response.is_error
            or not response.content
            or any(kind in response.headers.get("content-type", "") for kind in ("json", "text/"))
        ):
            raise AudioGenerationError(
                f"YarnGPT returned no usable audio (status {response.status_code})"
            )
        return response.content


def _retry_after(response: httpx.Response, attempt: int) -> float:
    try:
        delay = float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        try:
            delay = float(response.json()["error"]["details"]["retry_after_seconds"])
        except (ValueError, KeyError, TypeError):
            delay = float(2 ** (attempt + 1))
    return max(1.0, delay) if 0 <= delay < float("inf") else 2.0
