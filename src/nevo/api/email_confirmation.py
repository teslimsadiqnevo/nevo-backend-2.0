"""An administrator proves they own the address they registered with.

The first account in a school holds the highest permissions in it - every
child's roster entry, every consent state, the adaptation log, the compliance
screen - and it was the only account that never proved ownership of its
address. A mistyped address at registration also left nobody able to recover
the account and no way to reach whoever does own it.

The ruling on what an unconfirmed administrator may do is deliberate: they can
read the console, and they can write nothing. A school owner who registers at
nine at night and cannot find the email abandons entirely if the door is shut,
so the door stays open and the writes do not.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, select, update

from nevo.api.auth import OptionalPrincipalDependency, PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_auth import _mailer as mailer
from nevo.api.product_common import actor_user
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import User
from nevo.db.models.auth import EmailConfirmation
from nevo.notifications.branding import render_email
from nevo.notifications.email import EmailDeliveryUnavailableError, ResendEmailDelivery
from nevo.notifications.links import admin_email_confirmation_url

router = APIRouter(prefix="/api/v1", tags=["auth"])

#: Long enough for a school owner to find the email the next morning, short
#: enough that a link in an old inbox is not a standing key to a tenant. Stated
#: in the email and on the expired screen, so nobody meets it as a surprise.
CONFIRMATION_LIFETIME = timedelta(hours=48)

#: A resend is one email, not a queue. Anything faster is a way to use Nevo to
#: post to somebody else's inbox.
RESEND_INTERVAL = timedelta(minutes=2)


class EmailConfirmationState(CamelResponse):
    """Where an administrator's address stands.

    Three outcomes rather than one error, because the console draws three
    different screens: a link that has run out, a link already used, and a
    link that never existed.
    """

    status: Literal["confirmed", "pending", "expired", "already_confirmed", "invalid"]
    email: str | None = None
    #: When the outstanding link stops working. Null once there is no link.
    expires_at: datetime | None = None
    #: What the screen tells a person to do next, in words they can act on.
    message: str


class ConfirmationToken(BaseModel):
    model_config = CAMEL_CONFIG

    token: Annotated[str, Field(min_length=10, max_length=200)]


class ResendRequest(BaseModel):
    """Who is asking for another link, when there is no session to say.

    The token is the credential. An expired link already identifies the
    account - that is why it works on /verify - and the new link goes to the
    address on the account, never to whoever presented the token. So holding
    an old link buys nothing except sending mail to its rightful owner, which
    is what the button is for.
    """

    model_config = CAMEL_CONFIG

    token: Annotated[str, Field(min_length=10, max_length=200)] | None = None


class EmailChange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: EmailStr


async def issue_confirmation(
    session: DatabaseSession,
    user: User,
    *,
    now: datetime | None = None,
) -> tuple[EmailConfirmation, str]:
    """Start a new confirmation and put every earlier one beyond use.

    Superseding rather than deleting: a link that was emailed and then
    replaced should say it is no longer the current one, which it cannot do
    if the row it refers to is gone.
    """

    issued_at = now or datetime.now(UTC)
    await session.execute(
        update(EmailConfirmation)
        .where(
            EmailConfirmation.user_id == user.id,
            EmailConfirmation.confirmed_at.is_(None),
            EmailConfirmation.superseded_at.is_(None),
        )
        .values(superseded_at=issued_at)
    )
    token = secrets.token_urlsafe(32)
    confirmation = EmailConfirmation(
        user_id=user.id,
        email=str(user.email),
        token_digest=_digest(token),
        expires_at=issued_at + CONFIRMATION_LIFETIME,
    )
    session.add(confirmation)
    return confirmation, token


async def send_confirmation(
    mailer: ResendEmailDelivery,
    *,
    to: str,
    token: str,
    admin_name: str | None,
) -> None:
    link = admin_email_confirmation_url(mailer.frontend_base_url, token=token)
    hours = int(CONFIRMATION_LIFETIME.total_seconds() // 3600)
    greeting = f"Hello {admin_name}," if admin_name else "Hello,"
    try:
        await mailer.send(
            to=to,
            subject="Confirm your email address for Nevo",
            text=(
                f"{greeting}\n\n"
                "Confirm this address so your school's Nevo workspace is yours "
                f"to run:\n{link}\n\n"
                f"The link works for {hours} hours. Until it is confirmed you "
                "can look around the console, but you cannot add classes, "
                "invite teachers or request parental consent.\n"
            ),
            html=render_email(
                heading="Confirm your email address",
                paragraphs=[
                    greeting,
                    "Confirm this address so your school's Nevo workspace is yours to run.",
                    f"The link works for {hours} hours. Until it is confirmed "
                    "you can look around the console, but you cannot add "
                    "classes, invite teachers or request parental consent.",
                ],
                cta=("Confirm my address", link),
            ),
        )
    except EmailDeliveryUnavailableError:
        # Registration is not failed over an email provider being down: the
        # account exists, and a resend is one button away.
        return


def _pending(confirmation: EmailConfirmation) -> EmailConfirmationState:
    return EmailConfirmationState(
        status="pending",
        email=confirmation.email,
        expires_at=confirmation.expires_at,
        message=(
            "We sent a link to "
            f"{confirmation.email}. Confirm it to start adding classes and "
            "inviting your team."
        ),
    )


@router.get("/admin/email-confirmation", response_model=EmailConfirmationState)
async def read_email_confirmation(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> EmailConfirmationState:
    """What the console shows an administrator about their own address."""

    user = await actor_user(session, principal)
    if user.email_confirmed_at is not None:
        return EmailConfirmationState(
            status="confirmed",
            email=str(user.email),
            message="Your email address is confirmed.",
        )
    confirmation = await _outstanding(session, user)
    if confirmation is None:
        return EmailConfirmationState(
            status="expired",
            email=str(user.email),
            message="Your confirmation link has run out. Send yourself a new one.",
        )
    return _pending(confirmation)


async def _outstanding(session: DatabaseSession, user: User) -> EmailConfirmation | None:
    outstanding: EmailConfirmation | None = await session.scalar(
        select(EmailConfirmation)
        .where(
            EmailConfirmation.user_id == user.id,
            EmailConfirmation.confirmed_at.is_(None),
            EmailConfirmation.superseded_at.is_(None),
            EmailConfirmation.expires_at > datetime.now(UTC),
        )
        .order_by(EmailConfirmation.created_at.desc())
    )
    return outstanding


@router.post(
    "/admin/email-confirmation/verify",
    response_model=EmailConfirmationState,
    # The handler has never taken a principal, but the document inherited the
    # global bearer and said it did, so the one route a signed-out person must
    # be able to call read as closed to them.
    openapi_extra={"security": []},
)
async def verify_email(
    payload: ConfirmationToken,
    session: DatabaseSession,
) -> EmailConfirmationState:
    """Confirm an address from the link in the email.

    Unauthenticated by design: the person following the link may be reading
    their mail on a phone they have never signed in on, and a confirmation
    that demands a session first is a confirmation nobody completes.

    The three failures are told apart, because "that did not work" leaves a
    school owner with nothing to do next.
    """

    confirmation = await session.scalar(
        select(EmailConfirmation).where(EmailConfirmation.token_digest == _digest(payload.token))
    )
    if confirmation is None:
        return EmailConfirmationState(
            status="invalid",
            message=(
                "This link does not belong to a Nevo account. Check you opened "
                "the most recent email we sent you."
            ),
        )
    if confirmation.confirmed_at is not None:
        return EmailConfirmationState(
            status="already_confirmed",
            email=confirmation.email,
            message="This address is already confirmed. You can sign in.",
        )
    expired = confirmation.expires_at <= datetime.now(UTC)
    if expired or confirmation.superseded_at is not None:
        return EmailConfirmationState(
            status="expired",
            email=confirmation.email,
            message=(
                "This link has run out. Sign in and send yourself a new one "
                "from the banner at the top of the console."
            ),
        )
    now = datetime.now(UTC)
    confirmation.confirmed_at = now
    user = await session.get(User, confirmation.user_id)
    if user is not None:
        user.email_confirmed_at = now
    await session.commit()
    return EmailConfirmationState(
        status="confirmed",
        email=confirmation.email,
        message="Your address is confirmed. Your workspace is open.",
    )


async def _who_is_asking(
    session: DatabaseSession,
    principal: object | None,
    payload: "ResendRequest | None",
) -> User:
    """The account this resend is for: the session's, or the token's.

    The token is looked up whatever state it is in - expired, superseded,
    already used - because every one of those is a person on the expired-link
    screen with a reason to want another email.
    """

    if principal is not None:
        return await actor_user(session, principal)  # type: ignore[arg-type]
    token = (payload.token if payload else None) or ""
    confirmation = (
        await session.scalar(
            select(EmailConfirmation).where(EmailConfirmation.token_digest == _digest(token))
        )
        if token
        else None
    )
    user = await session.get(User, confirmation.user_id) if confirmation is not None else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "confirmation_credential_required",
                "message": (
                    "Sign in, or open this page from the most recent email we "
                    "sent you, and we can send another link."
                ),
            },
        )
    return user


@router.post(
    "/admin/email-confirmation/resend",
    response_model=EmailConfirmationState,
    # Optional, not absent: the console calls this signed in, and the expired
    # link screen is reached from an email on a device that has never signed
    # in at all. Requiring a session there meant the one screen that exists to
    # offer a new link could not offer one.
    openapi_extra={"security": [{"HTTPBearer": []}, {}]},
    responses={
        401: {
            "description": (
                "confirmation_credential_required when neither a session nor a "
                "recognised confirmation token was presented"
            )
        },
        429: {
            "description": (
                "confirmation_recently_sent, with retryAfterSeconds. One email "
                "every two minutes per account, however it was asked for."
            )
        },
    },
)
async def resend_confirmation(
    request: Request,
    principal: OptionalPrincipalDependency,
    session: DatabaseSession,
    payload: ResendRequest | None = None,
) -> EmailConfirmationState:
    """Send the confirmation again, at most once every couple of minutes.

    Two ways in. Signed in, it is the banner in the console. Signed out, it is
    the expired-link screen, and the expired token is the credential - the
    same argument that makes it one on /verify, and safer here, because the
    only thing this does is post to the address already on the account.
    """

    user = await _who_is_asking(session, principal, payload)
    if user.email_confirmed_at is not None:
        return EmailConfirmationState(
            status="already_confirmed",
            email=str(user.email),
            message="Your email address is already confirmed.",
        )
    last_sent = await session.scalar(
        select(func.max(EmailConfirmation.created_at)).where(EmailConfirmation.user_id == user.id)
    )
    now = datetime.now(UTC)
    if last_sent is not None and now - last_sent < RESEND_INTERVAL:
        wait = int((RESEND_INTERVAL - (now - last_sent)).total_seconds())
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "confirmation_recently_sent",
                "message": (
                    f"We sent one a moment ago. Try again in {wait} seconds, "
                    "and check your spam folder meanwhile."
                ),
                "retryAfterSeconds": wait,
            },
        )
    confirmation, token = await issue_confirmation(session, user, now=now)
    await session.commit()
    await send_confirmation(
        mailer(request),
        to=str(user.email),
        token=token,
        admin_name=user.first_name,
    )
    return _pending(confirmation)


@router.patch("/admin/email", response_model=EmailConfirmationState)
async def change_email_before_confirmation(
    payload: EmailChange,
    request: Request,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> EmailConfirmationState:
    """Correct a mistyped address, which is why this exists at all.

    Only before confirmation. Changing a confirmed address is changing who
    owns the highest-permission account in a school, and that is not a field
    edit - it is a decision with its own ticket.
    """

    user = await actor_user(session, principal)
    if user.email_confirmed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "email_already_confirmed",
                "message": (
                    "This address is confirmed. Contact support to change the "
                    "address on an administrator account."
                ),
            },
        )
    wanted = str(payload.email).casefold()
    taken = await session.scalar(
        select(User.id).where(func.lower(User.email) == wanted, User.id != user.id)
    )
    if taken is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "email_already_in_use",
                "message": "That address already belongs to a Nevo account.",
            },
        )
    user.email = wanted
    confirmation, token = await issue_confirmation(session, user)
    await session.commit()
    await send_confirmation(
        mailer(request),
        to=wanted,
        token=token,
        admin_name=user.first_name,
    )
    return _pending(confirmation)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
