"""Every link the backend puts in an email, built in one place.

A parent received a consent email whose link led to a page that does not
exist: the backend sent ``/consent/parent`` and the app serves
``/parent/consent``. The path lived inline in the service that sent the mail,
so nothing compared it against the app's routes and nothing failed when it
drifted.

The paths below are the app's, checked against the deployed frontend. A change
to one is a change to this file, and the tests next to it are the contract.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

#: Where a parent answers a consent request. Verified: the app serves it.
PARENT_CONSENT_PATH = "/parent/consent"

#: Where an invited teacher or admin finishes setting up their account.
JOIN_PATH = "/join"

#: Where an administrator confirms they own the address they registered with.
ADMIN_EMAIL_CONFIRMATION_PATH = "/admin/confirm-email"

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
    return _url(base_url, PARENT_CONSENT_PATH, token=token)


def join_url(base_url: str, *, token: str) -> str:
    """The token is in the path here, not the query, as the app expects."""
    return _url(base_url, f"{JOIN_PATH}/{quote(token, safe='')}")


def admin_email_confirmation_url(base_url: str, *, token: str) -> str:
    return _url(base_url, ADMIN_EMAIL_CONFIRMATION_PATH, token=token)


def password_reset_url(base_url: str, *, token: str) -> str:
    return _url(base_url, PASSWORD_RESET_PATH, token=token)
