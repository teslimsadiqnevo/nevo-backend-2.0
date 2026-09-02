

def _lead():
    from datetime import UTC, datetime
    from uuid import uuid4

    from nevo.domain.partner_inquiries.vocabulary import (
        PartnerInquiryContactMethod,
        PartnerInquiryIntent,
        PartnerInquiryRole,
        PartnerInquirySource,
    )
    from nevo.partner_inquiries.entities import PartnerInquiryView

    return PartnerInquiryView(
        id=uuid4(),
        full_name="Mrs Adaeze Nwosu",
        school_name="Brightside Academy, Lekki",
        role=PartnerInquiryRole.PROPRIETOR,
        contact="adaeze@brightside.ng",
        contact_method=PartnerInquiryContactMethod.EMAIL,
        message="We run three campuses.",
        created_at=datetime(2026, 9, 3, 10, 42, tzinfo=UTC),
        email="adaeze@brightside.ng",
        phone="+2348031234567",
        student_count=420,
        intent=PartnerInquiryIntent.FOUNDING_PARTNER,
        source=PartnerInquirySource.TOSSE_2026,
    )


def test_the_alert_leads_with_the_school_and_the_intent() -> None:
    """Read on a phone mid-conversation: those two identify who is standing
    in front of you and how the conversation should go."""
    from nevo.partner_inquiries.notifier import LeadEmailNotifier

    html = LeadEmailNotifier.html_summary(_lead())
    school = html.index("Brightside Academy, Lekki")
    intent = html.index("Founding Partner")

    assert school < intent < html.index("Mrs Adaeze Nwosu")


def test_phone_and_email_are_tap_to_act() -> None:
    """The realistic next step is calling them, not reading."""
    from nevo.partner_inquiries.notifier import LeadEmailNotifier

    html = LeadEmailNotifier.html_summary(_lead())

    assert 'href="tel:+2348031234567"' in html
    assert 'href="mailto:adaeze@brightside.ng"' in html


def test_the_alert_survives_a_mail_client_that_strips_styles() -> None:
    """Every client strips stylesheets and many ignore modern layout, so the
    styling is inline and the structure is a table."""
    from nevo.partner_inquiries.notifier import LeadEmailNotifier

    html = LeadEmailNotifier.html_summary(_lead())

    assert "<style" not in html
    assert "class=" not in html
    assert "<table" in html


def test_a_sparse_lead_does_not_render_empty_rows() -> None:
    """The website form sends far less than the TOSSE form."""
    import dataclasses

    from nevo.partner_inquiries.notifier import LeadEmailNotifier

    sparse = dataclasses.replace(
        _lead(), phone=None, student_count=None, message=None, intent=None
    )
    html = LeadEmailNotifier.html_summary(sparse)

    assert "tel:" not in html
    assert "Their note" not in html
    assert "Not stated" in html
    assert "Brightside Academy, Lekki" in html


def test_the_plain_text_version_still_stands_alone() -> None:
    """It is what a text-only client renders, so it cannot become a stub."""
    from nevo.partner_inquiries.notifier import LeadEmailNotifier

    text = LeadEmailNotifier.summary(_lead())

    assert "Brightside Academy, Lekki" in text
    assert "adaeze@brightside.ng" in text
    assert "<" not in text
