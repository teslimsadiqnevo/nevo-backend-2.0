from pydantic import AnyHttpUrl, Field, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class VisualGenerationSettings(BaseSettings):
    """Configuration for generated lesson imagery.

    Images come from a dedicated image model; every candidate is then reviewed
    by Claude vision against the lesson text before it is accepted, so a
    factually wrong or unreadable diagram never reaches a learner.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("https://api.openai.com/v1"),
        validation_alias="OPENAI_BASE_URL",
    )
    image_model: str = Field(default="gpt-image-2", validation_alias="IMAGE_GENERATION_MODEL")
    image_quality: str = Field(default="high", validation_alias="IMAGE_GENERATION_QUALITY")
    image_size: str = Field(default="1536x1024", validation_alias="IMAGE_GENERATION_SIZE")
    max_attempts: PositiveInt = Field(default=3, validation_alias="IMAGE_GENERATION_MAX_ATTEMPTS")

    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="AI_ANTHROPIC_API_KEY",
    )
    anthropic_base_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("https://api.anthropic.com/v1"),
        validation_alias="AI_ANTHROPIC_BASE_URL",
    )
    anthropic_version: str = Field(
        default="2023-06-01",
        validation_alias="AI_ANTHROPIC_VERSION",
    )
    validator_model: str = Field(
        default="claude-opus-4-8",
        validation_alias="IMAGE_VALIDATOR_MODEL",
    )

    supabase_url: AnyHttpUrl | None = Field(default=None, validation_alias="SUPABASE_URL")
    supabase_service_role_key: SecretStr | None = Field(
        default=None,
        validation_alias="SUPABASE_SERVICE_ROLE_KEY",
    )
    storage_bucket: str = Field(
        default="lesson-media",
        validation_alias="SUPABASE_STORAGE_BUCKET",
    )
    storage_public: bool = Field(default=True, validation_alias="SUPABASE_STORAGE_PUBLIC")
    signed_url_ttl_seconds: int = Field(
        default=604_800,
        validation_alias="SUPABASE_SIGNED_URL_TTL_SECONDS",
    )
