"""Every link the backend puts in an email, built in one place.

A parent received a consent email whose link led to a page that does not
exist: the backend sent ``/consent/parent?token=`` and the app serves
``/parent/<token>``. The path lived inline in the service that sent the mail,
so nothing compared it against the app's routes and nothing failed when it
drifted.

The paths below are the app's, checked against the deployed frontend. A change
to one is a change to this file, and the tests next to it are the contract.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

#: Where a parent answers a consent request.
#:
#: The token is a path segment, not a query parameter. Verified against the
#: deployed app rather than guessed a second time: opening /parent/<x> makes
#: it call GET /api/v1/consents/parent/<x>, so the last segment IS the token.
#: The first attempt at this fix sent /consent/parent?token=..., which the
#: app read as the token "consent" and looked up a consent that cannot exist.
PARENT_CONSENT_PATH = "/parent"

#: Where an invited teacher or admin finishes setting up their account.
JOIN_PATH = "/join"

#: Where an administrator confirms they own the address they registered with.
#:
#: The token is a path segment here too, the same shape as the parent link:
#: /auth/admin/confirm/<token>. Confirmed by the frontend against the route it
#: built, not guessed - the earlier ?token= spelling would have landed on a
#: route that does not exist once the screen ships (SCRUM-151).
ADMIN_EMAIL_CONFIRMATION_PATH = "/auth/admin/confirm"

#: Where a password reset lands.
#:
#: Unverified: the deployed app answers 404 for this and for every spelling of
#: it tried, so the screen appears not to exist yet. Left as it was rather than
#: swapped for a different guess; raised with the frontend.
PASSWORD_RESET_PATH = "/reset-password"


def _url(base_url: str, path: str, **query: str) -> str:
    link = f"{base_url.rstrip('/')}{path}"
    return f"{link}?{urlencode(query)}" if query else link


def parent_consent_url(base_url: str, *, token: str) -> str:
    """The token goes in the path, the way the app reads it."""

    return _url(base_url, f"{PARENT_CONSENT_PATH}/{quote(token, safe='')}")


def join_url(base_url: str, *, token: str) -> str:
    """The token is in the path here, not the query, as the app expects."""
    return _url(base_url, f"{JOIN_PATH}/{quote(token, safe='')}")


def admin_email_confirmation_url(base_url: str, *, token: str) -> str:
    """The token goes in the path, as the admin confirmation screen reads it."""

    return _url(base_url, f"{ADMIN_EMAIL_CONFIRMATION_PATH}/{quote(token, safe='')}")


def password_reset_url(base_url: str, *, token: str) -> str:
    return _url(base_url, PASSWORD_RESET_PATH, token=token)
