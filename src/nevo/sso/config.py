from pydantic import AnyHttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SsoSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SSO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    public_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")
    school_base_url: AnyHttpUrl = AnyHttpUrl("https://nevo.app")
    microsoft_client_secret: SecretStr | None = None
    google_client_secret: SecretStr | None = None
