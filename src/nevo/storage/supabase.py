from typing import Any
from urllib.parse import quote

import httpx

MAX_SIGNED_URL_TTL_SECONDS = 604_800
"""Supabase refuses signed URLs that outlive seven days."""


class StorageError(RuntimeError):
    pass


class SupabaseStorage:
    """Object storage for generated lesson media.

    Public buckets are addressed directly. Private buckets are addressed with a
    short-lived signed URL, so a browser can play or render the object without
    ever holding the service-role key.
    """

    def __init__(
        self,
        *,
        base_url: str | None,
        service_role_key: str | None,
        bucket: str,
        public: bool,
        signed_url_ttl_seconds: int = 3_600,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._service_role_key = service_role_key
        self._bucket = bucket
        self._public = public
        self._signed_url_ttl_seconds = min(
            max(signed_url_ttl_seconds, 1),
            MAX_SIGNED_URL_TTL_SECONDS,
        )

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._service_role_key)

    @property
    def public(self) -> bool:
        return self._public

    @property
    def signed_url_ttl_seconds(self) -> int:
        return self._signed_url_ttl_seconds

    async def exists(self, path: str) -> bool:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.head(self._object_endpoint(path), headers=self._headers())
        return response.is_success

    async def upload(self, path: str, content: bytes, *, content_type: str) -> None:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self._object_endpoint(path),
                headers={
                    **self._headers(),
                    "Content-Type": content_type,
                    "x-upsert": "true",
                },
                content=content,
            )
        if response.is_error:
            raise StorageError(f"Supabase upload failed with status {response.status_code}")

    async def url_for(self, path: str) -> str:
        """Return a URL a client can fetch directly.

        Public buckets get a stable public URL; private buckets get a signed URL
        that expires after ``signed_url_ttl_seconds``.
        """
        if self._public:
            return self.public_url(path)
        return await self.signed_url(path)

    def public_url(self, path: str) -> str:
        return f"{self._require_base_url()}/storage/v1/object/public/{self._object_path(path)}"

    async def signed_url(self, path: str, *, expires_in: int | None = None) -> str:
        base = self._require_base_url()
        ttl = self._signed_url_ttl_seconds if expires_in is None else expires_in
        ttl = min(max(ttl, 1), MAX_SIGNED_URL_TTL_SECONDS)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{base}/storage/v1/object/sign/{self._object_path(path)}",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"expiresIn": ttl},
            )
        if response.is_error:
            raise StorageError(
                f"Supabase signed URL request failed with status {response.status_code}"
            )
        try:
            payload: Any = response.json()
            signed = payload["signedURL"]
        except (KeyError, TypeError, ValueError) as error:
            raise StorageError("Supabase returned no signed URL") from error
        if not isinstance(signed, str) or not signed:
            raise StorageError("Supabase returned no signed URL")
        if signed.startswith("http://") or signed.startswith("https://"):
            return signed
        return f"{base}/storage/v1{signed if signed.startswith('/') else f'/{signed}'}"

    def _headers(self) -> dict[str, str]:
        if self._service_role_key is None:
            raise StorageError("Supabase Storage is not configured")
        return {
            "apikey": self._service_role_key,
            "Authorization": f"Bearer {self._service_role_key}",
        }

    def _require_base_url(self) -> str:
        if self._base_url is None:
            raise StorageError("Supabase Storage is not configured")
        return self._base_url

    def _object_path(self, path: str) -> str:
        return f"{quote(self._bucket, safe='')}/{quote(path, safe='/')}"

    def _object_endpoint(self, path: str) -> str:
        return f"{self._require_base_url()}/storage/v1/object/{self._object_path(path)}"
