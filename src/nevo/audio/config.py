from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AudioSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    yarngpt_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="YARNGPT_API_KEY",
    )
    yarngpt_api_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("https://yarngpt.ai/api/v1/tts"),
        validation_alias="YARNGPT_API_URL",
    )
    yarngpt_voice: str = Field(default="Idera", validation_alias="YARNGPT_VOICE")
    supabase_url: AnyHttpUrl | None = Field(
        default=None,
        validation_alias="SUPABASE_URL",
    )
    supabase_service_role_key: SecretStr | None = Field(
        default=None,
        validation_alias="SUPABASE_SERVICE_ROLE_KEY",
    )
    supabase_storage_bucket: str = Field(
        default="lesson-media",
        validation_alias="SUPABASE_STORAGE_BUCKET",
    )
    supabase_storage_public: bool = Field(
        default=True,
        validation_alias="SUPABASE_STORAGE_PUBLIC",
    )
    supabase_signed_url_ttl_seconds: int = Field(
        default=604_800,
        validation_alias="SUPABASE_SIGNED_URL_TTL_SECONDS",
    )
