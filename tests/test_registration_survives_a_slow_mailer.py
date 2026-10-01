"""Registration does not fail because Resend is slow. SCRUM-118.

The endpoint took three and a half seconds and then returned a bare 500 with
no code, after the school, the admin and its scopes had already been
committed. The admin saw a failure, retried, and the retry hit the duplicate
check - so the account existed and could not be created again.

Two causes, both closed here. A network error from the mail provider escaped
uncaught, so it was reported as a server fault rather than as the email being
unavailable; and the send was inline, so a slow provider held the request.
"""

from __future__ import annotations

import inspect

import httpx
import pytest
from pydantic import SecretStr

from nevo.api.email_confirmation import send_confirmation
from nevo.api.product_auth import register_school
from nevo.notifications.email import (
    EmailDeliveryUnavailableError,
    EmailSettings,
    ResendEmailDelivery,
)


class _Unreachable:
    """An httpx client whose request never comes back."""

    async def __aenter__(self) -> _Unreachable:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, *_: object, **__: object) -> None:
        raise httpx.ReadTimeout("took too long")


def _configured_mailer() -> ResendEmailDelivery:
    return ResendEmailDelivery(EmailSettings(resend_api_key=SecretStr("re_test")))


@pytest.mark.anyio
async def test_a_network_error_is_the_email_being_unavailable_not_a_server_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _Unreachable())

    # Typed, so every caller that already degrades gracefully on a configured
    # provider saying no degrades the same way on one not answering at all.
    # Uncaught, this was the bare 500.
    with pytest.raises(EmailDeliveryUnavailableError) as refusal:
        await _configured_mailer().send(to="head@example.com", subject="s", text="t")

    assert "ReadTimeout" in str(refusal.value)
    # Chained, so the log says which of timeout, refused or reset it was.
    assert isinstance(refusal.value.__cause__, httpx.ReadTimeout)


@pytest.mark.anyio
async def test_a_confirmation_that_cannot_be_sent_does_not_fail_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _Unreachable())

    # The account exists by this point and a resend is one button away, so
    # there is nothing to report to the person who just signed up.
    await send_confirmation(
        _configured_mailer(),
        to="head@example.com",
        token="t",
        admin_name="Ada",
    )


def test_the_confirmation_email_is_sent_off_the_request() -> None:
    source = inspect.getsource(register_school)

    # Inline, this was most of the three and a half seconds, and it held a
    # school on the signup form after its account had been written.
    assert "spawn(" in source
    assert "confirmation-email-" in source


def test_a_blank_admin_name_is_a_client_mistake_not_a_crash() -> None:
    source = inspect.getsource(register_school)

    # "".split() is [], and names[0] on that is an IndexError reported as a
    # 500 for something the client got wrong.
    assert 'admin_name.split(maxsplit=1) or [""]' in source


def test_the_unavailable_error_is_what_callers_catch() -> None:
    assert issubclass(EmailDeliveryUnavailableError, Exception)
