"""Parent consent delivery transport tests."""
import httpx
import pytest
from pydantic import SecretStr

from nevo.consent.delivery import SmsSettings, TermiiSmsDelivery
from nevo.consent.worker import EMAIL_SUBJECT, consent_message


def _mock_httpx(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(recording)
    original_client = httpx.AsyncClient

    def client(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return requests


def test_sms_is_unconfigured_without_an_api_key() -> None:
    assert not TermiiSmsDelivery(SmsSettings()).configured


async def test_unconfigured_sms_refuses_to_send() -> None:
    with pytest.raises(RuntimeError):
        await TermiiSmsDelivery(SmsSettings()).send(to="+2348012345678", text="hello")


async def test_sms_posts_the_consent_message(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = _mock_httpx(monkeypatch, lambda request: httpx.Response(200))
    settings = SmsSettings(TERMII_API_KEY=SecretStr("termii-secret"), TERMII_SENDER_ID="Nevo")

    await TermiiSmsDelivery(settings).send(to="+2348012345678", text="hello")

    assert len(requests) == 1
    assert requests[0].url.host == "v3.api.termii.com"
    body = requests[0].content.decode()
    assert "termii-secret" in body
    assert "+2348012345678" in body


async def test_sms_raises_when_the_provider_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_httpx(monkeypatch, lambda request: httpx.Response(402))
    settings = SmsSettings(TERMII_API_KEY=SecretStr("termii-secret"))

    with pytest.raises(RuntimeError, match="402"):
        await TermiiSmsDelivery(settings).send(to="+2348012345678", text="hello")


def test_consent_message_carries_the_link_and_expiry() -> None:
    message = consent_message("https://app.nevo.test/consent/parent?token=abc")

    assert "https://app.nevo.test/consent/parent?token=abc" in message
    assert "7 days" in message
    assert EMAIL_SUBJECT


def test_sms_sender_id_defaults_to_nevo() -> None:
    assert SmsSettings().termii_sender_id == "Nevo"
