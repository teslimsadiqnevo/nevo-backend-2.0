"""The highest-permission account in a school proves it owns its address.

It was the only account that never did, and a mistyped address at registration
left nobody able to recover it. The ruling on what an unconfirmed
administrator may do is the part worth guarding: read everything, write
nothing, with the rule on the server rather than in the interface.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from nevo.api.email_confirmation import CONFIRMATION_LIFETIME, RESEND_INTERVAL
from nevo.api.product_common import UNCONFIRMED_WRITE_ALLOWLIST, _refuse_unconfirmed_write
from nevo.api.request_context import set_request
from nevo.db.models.account import User
from nevo.db.models.auth import EmailConfirmation
from nevo.domain.accounts.vocabulary import UserRole
from nevo.main import app


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def _admin() -> User:
    return User(role=UserRole.OTHER_ADMIN, email="head@school.test", email_confirmed_at=None)


def test_the_console_can_draw_three_different_screens(spec: dict) -> None:
    states = spec["components"]["schemas"]["EmailConfirmationState"]["properties"]["status"]

    # Expired, already used and never valid are different things to be told.
    assert {"expired", "already_confirmed", "invalid"} <= set(states["enum"])


def test_there_is_a_verify_a_resend_and_a_change_of_address(spec: dict) -> None:
    assert "post" in spec["paths"]["/api/v1/admin/email-confirmation/verify"]
    assert "post" in spec["paths"]["/api/v1/admin/email-confirmation/resend"]
    assert "patch" in spec["paths"]["/api/v1/admin/email"]


def test_the_link_lasts_a_stated_and_sensible_time() -> None:
    # Long enough to find the email next morning, short enough that an old
    # inbox is not a standing key to a school's tenant.
    assert timedelta(hours=24) <= CONFIRMATION_LIFETIME <= timedelta(days=7)
    assert RESEND_INTERVAL >= timedelta(minutes=1)


def test_a_link_can_be_told_apart_from_its_replacement() -> None:
    columns = {column.name for column in EmailConfirmation.__table__.columns}

    assert {"confirmed_at", "superseded_at", "expires_at"} <= columns


def test_an_unconfirmed_administrator_may_read() -> None:
    set_request("GET", "/api/v1/classes")

    _refuse_unconfirmed_write(_admin())


def test_an_unconfirmed_administrator_may_not_write() -> None:
    from fastapi import HTTPException

    set_request("POST", "/api/v1/classes")

    with pytest.raises(HTTPException) as refusal:
        _refuse_unconfirmed_write(_admin())

    assert refusal.value.status_code == 403
    assert refusal.value.detail["code"] == "email_not_confirmed"


def test_the_way_out_of_the_blocked_state_is_not_blocked() -> None:
    for path in UNCONFIRMED_WRITE_ALLOWLIST:
        set_request("POST", path + "/resend")

        _refuse_unconfirmed_write(_admin())


def test_a_teacher_is_not_caught_by_a_rule_written_for_administrators() -> None:
    set_request("POST", "/api/v1/lessons")
    teacher = User(role=UserRole.TEACHER, email="teacher@school.test")

    _refuse_unconfirmed_write(teacher)


def test_work_that_is_not_a_request_is_not_a_write_by_a_person() -> None:
    # Workers and scheduled jobs run outside any request. A rule about what a
    # person may write does not apply to them.
    from nevo.api.request_context import _REQUEST

    _REQUEST.set(None)

    _refuse_unconfirmed_write(_admin())


def test_registration_sends_the_confirmation() -> None:
    import inspect

    from nevo.api.product_auth import register_school

    source = inspect.getsource(register_school)

    assert "_start_email_confirmation" in source
    assert "_send_email_confirmation" in source


def test_the_two_signed_out_screens_are_declared_signed_out(spec: dict) -> None:
    """A person following a link from their inbox has no session.

    /verify never took a principal, but the document inherited the global
    bearer and said it did, so the one route a signed-out person must be able
    to call read as closed to them. /resend now accepts either.
    """

    verify = spec["paths"]["/api/v1/admin/email-confirmation/verify"]["post"]
    resend = spec["paths"]["/api/v1/admin/email-confirmation/resend"]["post"]

    assert verify["security"] == []
    # Either a bearer, or nothing: the console banner and the expired-link
    # screen are the same button on two different sides of a sign-in.
    assert {} in resend["security"]
    assert {"HTTPBearer": []} in resend["security"]


def test_the_resend_takes_a_token_for_the_signed_out_case(spec: dict) -> None:
    resend = spec["paths"]["/api/v1/admin/email-confirmation/resend"]["post"]
    body = spec["components"]["schemas"]["ResendRequest"]["properties"]["token"]

    assert resend["requestBody"] is not None
    # Optional: the console sends no body at all and still works.
    assert not spec["components"]["schemas"]["ResendRequest"].get("required")
    assert any(arm.get("type") == "string" for arm in body["anyOf"])


def test_a_resend_with_neither_credential_is_refused(spec: dict) -> None:
    resend = spec["paths"]["/api/v1/admin/email-confirmation/resend"]["post"]

    assert "401" in resend["responses"]
    assert "confirmation_credential_required" in resend["responses"]["401"]["description"]


def test_the_rate_limit_is_declared_because_a_client_has_to_draw_it(spec: dict) -> None:
    resend = spec["paths"]["/api/v1/admin/email-confirmation/resend"]["post"]

    assert "429" in resend["responses"]
    assert "retryAfterSeconds" in resend["responses"]["429"]["description"]


def test_a_resend_never_sends_anywhere_but_the_account_address() -> None:
    """The whole safety of token-authenticated resend rests on this.

    Holding an old link must buy nothing except posting to its rightful
    owner's inbox, so the destination comes from the user row and never from
    anything the caller sent.
    """

    import inspect

    from nevo.api.email_confirmation import resend_confirmation

    source = inspect.getsource(resend_confirmation)

    assert "to=str(user.email)" in source
    assert "payload.email" not in source


def test_changing_the_address_still_needs_a_session(spec: dict) -> None:
    """Deliberately not relaxed alongside the resend.

    A resend posts to the address already on file. A change of address moves
    where the account can be recovered from, and an unconfirmed admin can
    reset their password by email - so a leaked link that could also change
    the address would be a route to the whole tenant.
    """

    change = spec["paths"]["/api/v1/admin/email"]["patch"]

    assert change["security"] == [{"HTTPBearer": []}]
