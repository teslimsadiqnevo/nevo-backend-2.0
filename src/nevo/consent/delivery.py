import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SmsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    termii_api_key: SecretStr | None = Field(default=None, alias="TERMII_API_KEY")
    termii_sender_id: str = Field(default="Nevo", alias="TERMII_SENDER_ID")


class TermiiSmsDelivery:
    def __init__(self, settings: SmsSettings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        return self._settings.termii_api_key is not None

    async def send(self, *, to: str, text: str) -> None:
        key = self._settings.termii_api_key
        if key is None:
            raise RuntimeError("SMS delivery is not configured")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://v3.api.termii.com/api/sms/send",
                json={
                    "api_key": key.get_secret_value(),
                    "to": to,
                    "from": self._settings.termii_sender_id,
                    "sms": text,
                    "type": "plain",
                    "channel": "generic",
                },
            )
        if response.is_error:
            raise RuntimeError(f"SMS provider rejected delivery ({response.status_code})")
