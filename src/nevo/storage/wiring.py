from nevo.audio.config import AudioSettings
from nevo.storage.media import LessonMediaService
from nevo.storage.supabase import SupabaseStorage


def build_supabase_storage(settings: AudioSettings | None = None) -> SupabaseStorage:
    resolved = settings or AudioSettings()
    key = resolved.supabase_service_role_key
    return SupabaseStorage(
        base_url=str(resolved.supabase_url) if resolved.supabase_url else None,
        service_role_key=key.get_secret_value() if key else None,
        bucket=resolved.supabase_storage_bucket,
        public=resolved.supabase_storage_public,
        signed_url_ttl_seconds=resolved.supabase_signed_url_ttl_seconds,
    )


def build_lesson_media_service(settings: AudioSettings | None = None) -> LessonMediaService:
    return LessonMediaService(build_supabase_storage(settings))
