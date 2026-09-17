"""Every email Nevo sends looks like Nevo sent it.

All of them went out as plain text: correct, delivered, and indistinguishable
from a script. That matters most on the messages that ask somebody to click -
a consent request mentioning their child, a sign-in code, a password reset -
because a parent has no other way to tell a real one from a forgery.
"""

from __future__ import annotations

import inspect
import re

import pytest

from nevo.notifications.branding import LOGO_URL, render_email

SENDERS = [
    ("nevo.api.frontend_unblockers", "request_password_reset"),
    ("nevo.api.product_auth", "_deliver_parent_code"),
    ("nevo.consent.worker", "ConsentDeliveryWorker"),
    ("nevo.notifications.worker", "NotificationEmailWorker"),
    ("nevo.partner_inquiries.notifier", "LeadEmailNotifier"),
]


@pytest.mark.parametrize("module_name,attribute", SENDERS)
def test_every_sender_sends_html(module_name: str, attribute: str) -> None:
    import importlib

    source = inspect.getsource(getattr(importlib.import_module(module_name), attribute))

    assert "html=" in source, f"{attribute} still sends plain text only"


def test_the_plain_text_part_is_never_dropped() -> None:
    # It is what a screen reader, a watch and a client with images off render.
    from nevo.notifications.email import ResendEmailDelivery

    signature = inspect.signature(ResendEmailDelivery.send)

    assert signature.parameters["text"].default is inspect.Parameter.empty
    assert signature.parameters["html"].default is None


class TestTheShell:
    def test_it_carries_the_logo_from_a_url_that_resolves_directly(self) -> None:
        # nevolearning.com redirects to www, and a mail client that will not
        # follow a redirect for an image shows a broken one instead.
        assert LOGO_URL.startswith("https://www.nevolearning.com/")
        assert "<img" in render_email(heading="A", paragraphs=["b"])

    def test_it_escapes_what_callers_pass_through(self) -> None:
        # Several callers pass a school name or a teacher's own words.
        html = render_email(
            heading='Ada & "Co" <script>',
            paragraphs=["1 < 2 & 3 > 2"],
        )

        assert "<script>" not in html
        assert "&amp;" in html

    def test_a_button_is_a_table_not_a_padded_anchor(self) -> None:
        # A padded anchor collapses in Outlook, which is what a school office
        # is most likely to be reading this in.
        html = render_email(
            heading="Reset", paragraphs=["x"], cta=("Reset it", "https://n.test/r?t=1")
        )

        assert "https://n.test/r?t=1" in html
        assert re.search(r"<table[^>]*>.*?Reset it.*?</table>", html, re.S)

    def test_it_uses_inline_styles_only(self) -> None:
        # Mail clients strip stylesheets, so a <style> block is a silent
        # downgrade to unstyled text.
        html = render_email(heading="A", paragraphs=["b"])

        assert "<style" not in html
        assert "style=" in html

    def test_a_preheader_is_hidden_from_the_body(self) -> None:
        html = render_email(heading="A", paragraphs=["b"], preheader="Expires in 10 minutes")

        assert "Expires in 10 minutes" in html
        assert "display:none" in html
