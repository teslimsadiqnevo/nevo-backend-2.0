import asyncio
import smtplib
from email.message import EmailMessage

from pydantic import AnyHttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmailSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EMAIL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    from_address: str | None = None
    use_starttls: bool = True
    frontend_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:3000")


class EmailDeliveryUnavailableError(RuntimeError):
    pass


class SmtpEmailDelivery:
    def __init__(self, settings: EmailSettings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        return bool(self._settings.smtp_host and self._settings.from_address)

    @property
    def frontend_base_url(self) -> str:
        return str(self._settings.frontend_base_url).rstrip("/")

    async def send(self, *, to: str, subject: str, text: str) -> None:
        if not self.configured:
            raise EmailDeliveryUnavailableError("Email delivery is not configured")
        await asyncio.to_thread(self._send_sync, to=to, subject=subject, text=text)

    def _send_sync(self, *, to: str, subject: str, text: str) -> None:
        message = EmailMessage()
        message["From"] = self._settings.from_address
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        password = (
            self._settings.smtp_password.get_secret_value()
            if self._settings.smtp_password is not None
            else None
        )
        with smtplib.SMTP(
            self._settings.smtp_host,
            self._settings.smtp_port,
            timeout=20,
        ) as client:
            if self._settings.use_starttls:
                client.starttls()
            if self._settings.smtp_username:
                client.login(self._settings.smtp_username, password or "")
            client.send_message(message)
