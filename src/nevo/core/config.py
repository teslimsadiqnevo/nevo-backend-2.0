import os
from functools import lru_cache
from urllib.parse import unquote, urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The live project. Changed from ibavgeinubvmktxufvvr on 10 November, which
#: was the Ireland project the data was migrated away from. The guard below
#: refuses to let a non-production backend write to this one, and while the
#: constant named the old project it was guarding a database nothing was
#: using while leaving the live one open. Confirmed from /health at 12:51Z:
#: utskhzqynxepmlwkafxv, eu-west-2.
PRODUCTION_SUPABASE_PROJECT_REF = "utskhzqynxepmlwkafxv"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/nevo"
    #: Read here only to report it on /health; storage itself is configured
    #: per service. Named by SUPABASE_URL, separately from DATABASE_URL,
    #: which is how the two came to point at different projects.
    supabase_url: str | None = Field(default=None, validation_alias="SUPABASE_URL")
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
    focus_timing_verified: bool = Field(default=False, validation_alias="FOCUS_TIMING_VERIFIED")
    level_mastery_collection_enabled: bool = Field(
        default=False, validation_alias="LEVEL_MASTERY_COLLECTION_ENABLED"
    )
    level_aware_return_enabled: bool = Field(
        default=False, validation_alias="LEVEL_AWARE_RETURN_ENABLED"
    )

    @property
    def collect_level_mastery(self) -> bool:
        return self.focus_timing_verified and self.level_mastery_collection_enabled

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
        if self.is_production_runtime:
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

    @property
    def database_identity(self) -> dict[str, str]:
        """Which database this process is using, with nothing secret in it.

        Yinka, 10 November: the one thing that would have settled a day of
        guessing from outside. The code pins a production project ref and
        render.yaml declares it, but DATABASE_URL is set by hand per
        environment, so what a running service actually connected to was not
        knowable without the dashboard.

        Host and project ref only. No user, no password, no database name.
        """
        parsed = urlsplit(self.database_url)
        host = parsed.hostname or ""
        username = unquote(parsed.username or "")
        ref = username.removeprefix("postgres.") if username.startswith("postgres.") else ""
        if not ref and host.startswith("db.") and host.endswith(".supabase.co"):
            ref = host.removeprefix("db.").removesuffix(".supabase.co")
        # aws-0-eu-west-1.pooler.supabase.com -> eu-west-1
        region = ""
        if ".pooler.supabase.com" in host:
            first = host.split(".", 1)[0]
            region = first.split("-", 2)[-1] if "-" in first else first
        return {
            "host": host,
            "projectRef": ref,
            "region": region,
            "port": str(parsed.port or ""),
            "isPinnedProductionProject": str(
                bool(ref) and ref == self.production_supabase_project_ref
            ).casefold(),
        }

    @property
    def storage_identity(self) -> dict[str, str]:
        """Which Supabase project holds the files, and whether it matches the data.

        Yinka asked (11 November) whether /health could report this the way it
        reports the database's. It is the more useful of the two, because the
        two are set by separate variables and can drift: the database can be
        moved to a new project while SUPABASE_URL still names the old one,
        which leaves lessons in one project and their pictures and audio in
        another, each looking fine on its own.

        The URL is https://<project>.supabase.co and carries no region, so the
        region is not derivable here. The ref and whether it agrees with the
        database are what answer the question.
        """
        url = str(getattr(self, "supabase_url", "") or "")
        host = urlsplit(url).hostname or ""
        ref = host.removesuffix(".supabase.co") if host.endswith(".supabase.co") else ""
        database_ref = self.database_identity["projectRef"]
        return {
            "project": ref,
            "configured": str(bool(url)).casefold(),
            "matchesDatabase": str(bool(ref) and ref == database_ref).casefold(),
        }

    @property
    def is_production_runtime(self) -> bool:
        on_render_main = (
            os.environ.get("RENDER", "").strip().casefold() == "true"
            and os.environ.get("RENDER_GIT_BRANCH", "").strip().casefold() == "main"
            and os.environ.get("IS_PULL_REQUEST", "").strip().casefold() != "true"
        )
        return self.app_environment.strip().casefold() == "production" or on_render_main

    @property
    def run_deferred_media_worker(self) -> bool:
        return self.deferred_media_worker_enabled or self.is_production_runtime


@lru_cache
def get_settings() -> Settings:
    return Settings()
