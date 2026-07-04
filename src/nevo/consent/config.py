from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConsentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CONSENT_",
        env_file=".env",
        extra="ignore",
    )

    public_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:3000")
