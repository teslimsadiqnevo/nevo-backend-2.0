from nevo.storage.supabase import StorageError, SupabaseStorage

ALLOWED_PREFIXES = ("audio/", "images/")


class InvalidMediaPathError(ValueError):
    pass


class LessonMediaService:
    """Re-issues playable URLs for stored lesson media.

    Signed URLs expire, so a lesson parsed weeks ago can hold a dead link. The
    frontend refreshes one here rather than storing a service-role key.
    """

    def __init__(self, storage: SupabaseStorage) -> None:
        self._storage = storage

    @property
    def configured(self) -> bool:
        return self._storage.configured

    async def url_for(self, storage_path: str) -> tuple[str, int | None]:
        path = self._validate(storage_path)
        url = await self._storage.url_for(path)
        expires_in = None if self._storage.public else self._storage.signed_url_ttl_seconds
        return url, expires_in

    @staticmethod
    def _validate(storage_path: str) -> str:
        path = storage_path.strip().lstrip("/")
        if not path or ".." in path.split("/") or not path.startswith(ALLOWED_PREFIXES):
            raise InvalidMediaPathError(
                "storagePath must be a lesson media object under audio/ or images/"
            )
        return path


__all__ = [
    "ALLOWED_PREFIXES",
    "InvalidMediaPathError",
    "LessonMediaService",
    "StorageError",
]
