import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpsSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPS_",
        env_file=".env",
        extra="ignore",
    )

    self_ping_url: str | None = Field(
        default_factory=lambda: os.environ.get("RENDER_EXTERNAL_URL"),
    )
    self_ping_interval_seconds: float = 600.0
    heartbeat_check_interval_seconds: float = 3600.0
