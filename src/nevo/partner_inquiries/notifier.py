import logging

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from nevo.notifications.email import ResendEmailDelivery
from nevo.partner_inquiries.entities import PartnerInquiryView

logger = logging.getLogger(__name__)


class LeadAlertSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    #: Comma-separated. Empty means nobody is alerted and leads are still
    #: recorded, which is the right failure mode but a silent one.
    recipients: str = Field(default="", validation_alias="LEAD_ALERT_RECIPIENTS")

    @property
    def addresses(self) -> list[str]:
        return [item.strip() for item in self.recipients.split(",") if item.strip()]


class LeadEmailNotifier:
    """Emails whoever is working the booth as each lead arrives.

    Sending is best effort by design. The lead is committed before this runs,
    so a mail outage costs an alert, never a lead - and standing at a stand
    watching an inbox is not a system of record. The export is.
    """

    def __init__(
        self,
        *,
        delivery: ResendEmailDelivery,
        settings: LeadAlertSettings | None = None,
    ) -> None:
        self._delivery = delivery
        self._settings = settings or LeadAlertSettings()

    @property
    def configured(self) -> bool:
        return bool(self._settings.addresses) and self._delivery.configured

    async def notify(self, view: PartnerInquiryView) -> None:
        if not self.configured:
            return
        subject = f"New Nevo lead: {view.school_name}"
        for address in self._settings.addresses:
            try:
                await self._delivery.send(
                    to=address,
                    subject=subject,
                    text=self.summary(view),
                )
            except Exception:
                # Never propagate: the lead is already saved and the caller is
                # a school standing at the stand waiting for a confirmation.
                logger.warning("Lead alert to %s failed", address, exc_info=True)

    @staticmethod
    def summary(view: PartnerInquiryView) -> str:
        lines = [
            f"School:   {view.school_name}",
            f"Name:     {view.full_name}",
            f"Role:     {view.role.value.replace('_', ' ')}",
        ]
        if view.student_count is not None:
            lines.append(f"Students: {view.student_count}")
        if view.intent is not None:
            lines.append(f"Wants:    {view.intent.value.replace('_', ' ')}")
        if view.email:
            lines.append(f"Email:    {view.email}")
        if view.phone:
            lines.append(f"Phone:    {view.phone}")
        if view.message:
            lines.append(f"\nMessage:\n{view.message}")
        lines.append(f"\nSource:   {view.source.value}")
        lines.append(f"Received: {view.created_at:%d %B %H:%M UTC}")
        return "\n".join(lines)
