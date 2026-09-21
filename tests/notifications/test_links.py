"""The paths in emails, asserted against the app's real routes.

A parent's consent link pointed at a page that does not exist for as long as
nothing wrote the expected URL down. These are that record: if a path changes
here without the app changing, this fails.
"""

from nevo.notifications.links import (
    admin_email_confirmation_url,
    join_url,
    parent_consent_url,
    password_reset_url,
)

BASE = "https://www.nevolearning.com"


def test_parent_consent_link_is_the_route_the_app_serves() -> None:
    assert (
        parent_consent_url(BASE, token="abc123")
        == "https://www.nevolearning.com/parent/consent?token=abc123"
    )


def test_join_link_carries_the_token_in_the_path() -> None:
    assert join_url(BASE, token="abc123") == "https://www.nevolearning.com/join/abc123"


def test_admin_confirmation_link() -> None:
    assert (
        admin_email_confirmation_url(BASE, token="abc123")
        == "https://www.nevolearning.com/admin/confirm-email?token=abc123"
    )


def test_password_reset_link() -> None:
    assert (
        password_reset_url(BASE, token="abc123")
        == "https://www.nevolearning.com/reset-password?token=abc123"
    )


def test_a_trailing_slash_on_the_base_url_does_not_double_up() -> None:
    assert parent_consent_url(BASE + "/", token="t") == f"{BASE}/parent/consent?token=t"


def test_a_token_needing_escaping_survives_both_forms() -> None:
    token = "a b/c+d"
    assert parent_consent_url(BASE, token=token) == f"{BASE}/parent/consent?token=a+b%2Fc%2Bd"
    assert join_url(BASE, token=token) == f"{BASE}/join/a%20b%2Fc%2Bd"
