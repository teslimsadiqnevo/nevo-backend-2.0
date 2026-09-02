import httpx
from pydantic import AliasChoices, AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

RESEND_API_URL = "https://api.resend.com/emails"


class EmailSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    resend_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="RESEND_API_KEY",
    )
    from_address: str = Field(
        default="Nevo <noreply@nevolearning.com>",
        validation_alias=AliasChoices("RESEND_FROM_ADDRESS", "EMAIL_FROM_ADDRESS"),
    )
    frontend_base_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("http://localhost:3000"),
        validation_alias="EMAIL_FRONTEND_BASE_URL",
    )


class EmailDeliveryUnavailableError(RuntimeError):
    pass


class ResendEmailDelivery:
    def __init__(self, settings: EmailSettings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        return self._settings.resend_api_key is not None

    @property
    def frontend_base_url(self) -> str:
        return str(self._settings.frontend_base_url).rstrip("/")

    async def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        html: str | None = None,
    ) -> None:
        """Send one email.

        ``text`` is always sent and is what a plain-text client renders, so it
        has to stand on its own. ``html`` is optional and additive.
        """
        if self._settings.resend_api_key is None:
            raise EmailDeliveryUnavailableError("Resend email delivery is not configured")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                RESEND_API_URL,
                headers={
                    "Authorization": (
                        f"Bearer {self._settings.resend_api_key.get_secret_value()}"
                    ),
                    "Content-Type": "application/json",
                },
                json={
                    "from": self._settings.from_address,
                    "to": [to],
                    "subject": subject,
                    "text": text,
                    **({"html": html} if html else {}),
                },
            )
        if response.is_error:
            raise EmailDeliveryUnavailableError(
                f"Resend rejected the email with status {response.status_code}"
            )
