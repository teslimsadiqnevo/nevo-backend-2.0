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
    #: The Supabase project the media is meant to be in.
    #:
    #: The files stay on Supabase when the database moves to Render, so
    #: "storage matches the database" stops being a useful test and this
    #: replaces it. Left empty while the two are together, where the
    #: database's own ref is the right expectation.
    expected_storage_project: str = Field(default="", validation_alias="EXPECTED_STORAGE_PROJECT")

    #: The live database's host, for the guard above and for /health.
    #:
    #: Added for the move to Render Postgres, where there is no project ref
    #: to pin. While the database is still on Supabase both this and
    #: PRODUCTION_SUPABASE_PROJECT_REF can be set; either one matching means
    #: production, so the guard holds through the cutover rather than having
    #: a window where it protects nothing.
    production_database_host: str = Field(default="", validation_alias="PRODUCTION_DATABASE_HOST")
    safety_policy_v2_enabled: bool = Field(
        default=False, validation_alias="SAFETY_POLICY_V2_ENABLED"
    )
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

    def points_at_production_database(self) -> bool:
        """Whether this DATABASE_URL is the live database, whoever hosts it.

        Two tests, because the database is moving off Supabase and the guard
        has to hold on both sides of that. A Supabase project is named by the
        ref in the username or in a db.<ref>.supabase.co host; a Render
        database has no ref at all, so it is named by host.

        Keyed on host rather than on the full URL on purpose: the password
        rotates, the database name and user may differ between a connection
        string and a dashboard, and a guard that misses because one character
        changed is a guard nobody can rely on.
        """
        parsed = urlsplit(self.database_url)
        host = (parsed.hostname or "").casefold()
        ref = unquote(parsed.username or "").removeprefix("postgres.")
        pinned_ref = self.production_supabase_project_ref
        if pinned_ref and (ref == pinned_ref or host == f"db.{pinned_ref}.supabase.co".casefold()):
            return True
        pinned_host = self.production_database_host.strip().casefold()
        return bool(pinned_host) and host == pinned_host

    def assert_database_target_allowed(self) -> None:
        if self.is_production_runtime:
            return
        if self.points_at_production_database():
            raise RuntimeError(
                "Refusing to start a non-production backend against the live "
                "database. Set DATABASE_URL to a test database."
            )

    @property
    def database_identity(self) -> dict[str, str]:
        """Which database this process is using, with nothing secret in it.

        Yinka, 10 November: the one thing that would have settled a day of
        guessing from outside. DATABASE_URL is set by hand per environment,
        so what a running service had actually connected to was not knowable
        without the dashboard - and when I read it off the wrong host I got
        the answer wrong twice.

        Host, port, provider and project ref. No user, no password, no
        database name. projectRef and region are Supabase's way of naming a
        database and are empty on Render, which is why provider is reported
        beside them: an empty ref must read as "not Supabase" rather than as
        "unknown".
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
        if "supabase" in host:
            provider = "supabase"
        elif host.endswith(".render.com") or host.endswith(".onrender.com"):
            provider = "render"
        elif host in {"localhost", "127.0.0.1", "::1", ""}:
            provider = "local"
        else:
            provider = "other"
        return {
            "host": host,
            "provider": provider,
            "projectRef": ref,
            "region": region,
            "port": str(parsed.port or ""),
            # True when this is the live database, by ref or by host. The
            # name says "project" for the frontend check that already reads
            # it; it means the pinned production database either way.
            "isPinnedProductionProject": str(self.points_at_production_database()).casefold(),
        }

    @property
    def storage_identity(self) -> dict[str, str]:
        """Which Supabase project holds the files, and whether that is the one we meant.

        Yinka asked (11 November) whether /health could report this the way
        it reports the database's, and the first thing it found was a split:
        the database had moved projects while SUPABASE_URL still named the
        old one, leaving lessons in one project and their pictures in
        another, each looking healthy alone.

        "Matches the database" was the right test while both lived in the
        same Supabase project. It stops being the right test the moment the
        database moves to Render, because then they never match and a field
        that is permanently false is one people learn to ignore. So the
        comparison is against the storage project we intend - set by
        EXPECTED_STORAGE_PROJECT - and falls back to the database's own ref
        while the two are still together.

        The URL is https://<project>.supabase.co and carries no region, so
        the region is not derivable here.
        """
        url = str(getattr(self, "supabase_url", "") or "")
        host = urlsplit(url).hostname or ""
        ref = host.removesuffix(".supabase.co") if host.endswith(".supabase.co") else ""
        expected = (self.expected_storage_project or "").strip() or self.database_identity[
            "projectRef"
        ]
        return {
            "project": ref,
            "configured": str(bool(url)).casefold(),
            "expected": expected,
            "isExpectedProject": str(bool(ref) and ref == expected).casefold(),
            # Kept because the console reads it. Now says only whether the
            # files sit beside the data, which is informational once the
            # database moves and is deliberately false afterwards.
            "matchesDatabase": str(
                bool(ref) and ref == self.database_identity["projectRef"]
            ).casefold(),
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
