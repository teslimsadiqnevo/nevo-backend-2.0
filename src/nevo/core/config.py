from functools import lru_cache
from urllib.parse import unquote, urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PRODUCTION_SUPABASE_PROJECT_REF = "ibavgeinubvmktxufvvr"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/nevo"
    app_environment: str = Field(default="development", validation_alias="APP_ENV")
    deferred_media_worker_enabled: bool = Field(
        default=False, validation_alias="DEFERRED_MEDIA_WORKER_ENABLED"
    )
    production_supabase_project_ref: str = Field(
        default=PRODUCTION_SUPABASE_PROJECT_REF,
        validation_alias="PRODUCTION_SUPABASE_PROJECT_REF",
    )
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    cors_allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    comprehension_gate_enabled: bool = Field(
        default=False,
        validation_alias="COMPREHENSION_GATE_ENABLED",
        description=(
            "Hold lesson progress at missed checks only after the player supports all "
            "re-teaching routes and an always-reachable break."
        ),
    )

    @field_validator("database_url")
    @classmethod
    def normalize_database_driver(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    def assert_database_target_allowed(self) -> None:
        if self.app_environment.strip().casefold() == "production":
            return
        parsed = urlsplit(self.database_url)
        username = unquote(parsed.username or "")
        project_ref = username.removeprefix("postgres.")
        is_production_project = project_ref == self.production_supabase_project_ref or (
            parsed.hostname == f"db.{self.production_supabase_project_ref}.supabase.co"
        )
        if is_production_project:
            raise RuntimeError(
                "Refusing to start a non-production backend against the production "
                "Supabase project. Set DATABASE_URL to the test database."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
