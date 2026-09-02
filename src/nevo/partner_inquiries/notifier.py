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
                    html=self.html_summary(view),
                )
            except Exception:
                # Never propagate: the lead is already saved and the caller is
                # a school standing at the stand waiting for a confirmation.
                logger.warning("Lead alert to %s failed", address, exc_info=True)

    @staticmethod
    def html_summary(view: PartnerInquiryView) -> str:
        """A lead alert read on a phone, mid-conversation, at a stand.

        Built for a two-second glance rather than completeness: the school
        name is the headline because that is what identifies the person
        standing in front of you, and the intent sits next to it because it
        decides how the conversation goes. Phone and email are tap-to-act
        links, since the realistic next step is calling them, not reading.

        Deliberately a single table with inline styles - every mail client
        strips stylesheets, and half of them ignore flexbox.
        """
        intent = view.intent.value.replace("_", " ").title() if view.intent else "Not stated"
        rows = [("Contact", view.full_name), ("Role", view.role.value.replace("_", " ").title())]
        if view.student_count is not None:
            rows.append(("Students", f"{view.student_count:,}"))
        if view.phone:
            rows.append(("Phone", f'<a href="tel:{view.phone}" style="color:#4338CA;'
                                  f'text-decoration:none">{view.phone}</a>'))
        if view.email:
            rows.append(("Email", f'<a href="mailto:{view.email}" style="color:#4338CA;'
                                  f'text-decoration:none">{view.email}</a>'))
        cells = "".join(
            f'<tr><td style="padding:6px 16px 6px 0;color:#6B7280;font-size:14px;'
            f'white-space:nowrap;vertical-align:top">{label}</td>'
            f'<td style="padding:6px 0;color:#111827;font-size:15px;'
            f'font-weight:500">{value}</td></tr>'
            for label, value in rows
        )
        message = (
            f'<tr><td colspan="2" style="padding:14px 0 0">'
            f'<div style="color:#6B7280;font-size:13px;margin-bottom:4px">Their note</div>'
            f'<div style="color:#111827;font-size:15px;line-height:1.5;'
            f'background:#F9FAFB;border-radius:8px;padding:12px">{view.message}</div>'
            f"</td></tr>"
            if view.message
            else ""
        )
        font = (
            "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
        )
        card = (
            "max-width:520px;margin:0 auto;background:#FFFDF8;border-radius:14px;"
            "padding:24px;border:1px solid #E7E2D6"
        )
        eyebrow = (
            "color:#6B7280;font-size:12px;letter-spacing:.08em;"
            "text-transform:uppercase;margin-bottom:6px"
        )
        heading = "color:#111827;font-size:22px;font-weight:650;line-height:1.25"
        badge = (
            "display:inline-block;margin-top:10px;padding:4px 12px;background:#EEF2FF;"
            "color:#4338CA;border-radius:999px;font-size:13px;font-weight:600"
        )
        footer = (
            "margin-top:20px;padding-top:14px;border-top:1px solid #E7E2D6;"
            "color:#9CA3AF;font-size:12px"
        )
        received = f"{view.created_at:%d %b %Y, %H:%M}"
        return (
            f'<div style="background:#F4F1EA;padding:24px 16px;font-family:{font}">'
            f'<div style="{card}">'
            f'<div style="{eyebrow}">New lead</div>'
            f'<div style="{heading}">{view.school_name}</div>'
            f'<div style="{badge}">{intent}</div>'
            f'<table role="presentation" cellpadding="0" cellspacing="0"'
            f' style="margin-top:18px;width:100%">{cells}{message}</table>'
            f'<div style="{footer}">'
            f'{view.source.value.replace("_", " ")} &middot; {received} UTC'
            f"</div></div></div>"
        )

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
