"""Identity for an individual (/me) account: register, verify, who am I.

/me, Phase 1. A school identity is a school code, a Student ID and a PIN. An
individual identity is an email address, unique on its own, a password and
an ordinary emailed code. No school code is involved at any point.

Sign-in is the existing email-and-password route (POST /api/v1/auth/login or
/login/password); it returns the session shape the PIN route returns, so the
session layer is untouched. Password reset is the existing
/auth/password-reset/request and /complete pair, which already resolves an
account by address alone.

Registration, verification and resend are closed while
ME_REGISTRATION_ENABLED is off (the default): they answer 404 as if absent.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from nevo.api.account_scope import AccountType
from nevo.api.auth import (
    AuthServiceDependency,
    PrincipalDependency,
    SessionResponse,
    client_ip,
    public_auth_error,
)
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_auth import credential_hasher
from nevo.api.response_models import CamelResponse
from nevo.auth.errors import AuthError
from nevo.consent import guardian
from nevo.core.config import get_settings
from nevo.db.models.account import User
from nevo.db.models.auth import AuthLoginAttempt, EmailConfirmation
from nevo.domain.accounts.age_bands import age_on
from nevo.domain.accounts.vocabulary import AuthMethod, UserRole, UserStatus
from nevo.notifications import me_copy
from nevo.notifications.branding import render_email
from nevo.notifications.email import EmailDeliveryUnavailableError, ResendEmailDelivery

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

CODE_DIGITS = 6
CODE_LIFETIME = timedelta(minutes=30)

#: Wrong codes allowed per address in a window before verification pauses.
#: Five in fifteen minutes puts a million-code space years out of reach.
VERIFY_MAX_FAILURES = 5
VERIFY_WINDOW = timedelta(minutes=15)

#: The mail limiter: one code per interval, and a ceiling per day, per address.
#: Registration and resend share it, so neither can post to somebody else's
#: inbox faster than this.
RESEND_INTERVAL = timedelta(minutes=2)
RESENDS_PER_DAY = 5


# --------------------------------------------------------------------------
# Wire shapes


class RegisterRequest(BaseModel):
    model_config = CAMEL_CONFIG

    first_name: Annotated[str, Field(min_length=1, max_length=100)]
    last_name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=1024)]
    date_of_birth: date

    @field_validator("first_name", "last_name")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("date_of_birth")
    @classmethod
    def _plausible(cls, value: date) -> date:
        today = datetime.now(UTC).date()
        if value >= today:
            raise ValueError("must be in the past")
        if (age_on(value, today) or 0) > 120:
            raise ValueError("is not plausible")
        return value


class VerifyRequest(BaseModel):
    model_config = CAMEL_CONFIG

    email: EmailStr
    code: Annotated[str, Field(min_length=CODE_DIGITS, max_length=CODE_DIGITS, pattern=r"^\d+$")]


class VerificationResendRequest(BaseModel):
    model_config = CAMEL_CONFIG

    email: EmailStr


class Accepted(CamelResponse):
    status: Literal["accepted"] = "accepted"


class ConsentState(CamelResponse):
    """Whether this account needs a guardian's consent, and where it stands.

    ``required`` is false for an adult. For an under-18 it is outstanding,
    dormant after fourteen days unanswered, or granted once a guardian has
    consented (nevo.consent.guardian). GET /me/consent carries the detail.
    """

    required: bool
    state: Literal["not_required", "outstanding", "granted", "dormant"]


class WhoAmI(CamelResponse):
    """GET /auth/me. Absent rather than empty: school fields are omitted for
    an individual account, and ``consent`` is omitted for a school account,
    whose consent is held through the school."""

    user_id: UUID
    account_type: Literal["school", "individual"]
    role: str
    email: str | None = None
    email_verified: bool
    first_name: str | None = None
    last_name: str | None = None
    school_id: UUID | None = None
    consent: ConsentState | None = None


# --------------------------------------------------------------------------
# Helpers


def _closed_unless_enabled() -> None:
    if not get_settings().me_registration_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


def _normal(email: str) -> str:
    return email.strip().casefold()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _code_digest(confirmation_id: UUID, code: str) -> str:
    # Salted with the confirmation's own id: a six-digit code alone would
    # collide across accounts on the unique token_digest column.
    return _digest(f"me-verify:{confirmation_id}:{code}")


def _verify_identity(email: str) -> str:
    return _digest(f"me-verify-email:{email}")


async def _consent(session: DatabaseSession, user: User) -> ConsentState:
    view = await guardian.consent_view(session, user)
    return ConsentState(required=view.required, state=view.state)


def _too_many(retry_at: datetime) -> HTTPException:
    seconds = max(1, int((retry_at - datetime.now(UTC)).total_seconds()) + 1)
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "too_many_attempts",
            "message": "Too many attempts. Please wait before trying again.",
            "retryAt": retry_at.isoformat(),
        },
        headers={"Retry-After": str(seconds)},
    )


async def _mail_pause(session: DatabaseSession, user_id: UUID, now: datetime) -> datetime | None:
    """When the next code may be sent to this account, or None if now."""

    row = (
        await session.execute(
            select(func.count(), func.max(EmailConfirmation.created_at)).where(
                EmailConfirmation.user_id == user_id,
                EmailConfirmation.created_at >= now - timedelta(days=1),
            )
        )
    ).one()
    count, latest = int(row[0] or 0), row[1]
    if latest is not None and latest + RESEND_INTERVAL > now:
        return latest + RESEND_INTERVAL
    if count >= RESENDS_PER_DAY:
        oldest = await session.scalar(
            select(func.min(EmailConfirmation.created_at)).where(
                EmailConfirmation.user_id == user_id,
                EmailConfirmation.created_at >= now - timedelta(days=1),
            )
        )
        return (oldest or now) + timedelta(days=1)
    return None


async def _issue_code(session: DatabaseSession, user: User, now: datetime) -> str:
    await session.execute(
        update(EmailConfirmation)
        .where(
            EmailConfirmation.user_id == user.id,
            EmailConfirmation.confirmed_at.is_(None),
            EmailConfirmation.superseded_at.is_(None),
        )
        .values(superseded_at=now)
    )
    code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
    confirmation_id = uuid4()
    session.add(
        EmailConfirmation(
            id=confirmation_id,
            user_id=user.id,
            email=str(user.email),
            token_digest=_code_digest(confirmation_id, code),
            expires_at=now + CODE_LIFETIME,
            created_at=now,
        )
    )
    return code


async def _send_code(request: Request, user: User, code: str) -> None:
    mailer = getattr(request.app.state, "email_delivery", None)
    if not isinstance(mailer, ResendEmailDelivery):
        return
    minutes = int(CODE_LIFETIME.total_seconds() // 60)
    try:
        await mailer.send(
            to=str(user.email),
            subject=me_copy.VERIFY_SUBJECT,
            text=me_copy.verify_text(first_name=user.first_name, code=code, minutes=minutes),
            html=render_email(
                heading=me_copy.VERIFY_SUBJECT,
                paragraphs=me_copy.verify_paragraphs(
                    first_name=user.first_name, code=code, minutes=minutes
                ),
            ),
        )
    except EmailDeliveryUnavailableError:
        # The account exists and a resend is one button away; registration
        # is not failed over the email provider being down.
        return


async def _individual_by_email(session: DatabaseSession, email: str) -> User | None:
    return await session.scalar(
        select(User).where(
            func.lower(User.email) == email,
            User.account_type == AccountType.INDIVIDUAL.value,
        )
    )


# --------------------------------------------------------------------------
# Routes


@router.post("/register", response_model=Accepted, status_code=status.HTTP_202_ACCEPTED)
async def register(
    payload: RegisterRequest,
    request: Request,
    session: DatabaseSession,
) -> Accepted:
    """Create an unverified individual account and email it a code.

    The answer is the same 202 whether or not the address is already in use,
    and the password is hashed either way so the timing does not say either.
    An under-18 is registered, not refused (ruling A); their consent state is
    outstanding until a guardian consents (Phase 1b).
    """

    _closed_unless_enabled()
    email = _normal(str(payload.email))
    password_hash = await credential_hasher().hash_password_async(payload.password)

    taken = await session.scalar(select(User.id).where(func.lower(User.email) == email))
    if taken is not None:
        return Accepted()

    now = datetime.now(UTC)
    user = User(
        school_id=None,
        account_type=AccountType.INDIVIDUAL.value,
        role=UserRole.STUDENT,
        auth_method=AuthMethod.EMAIL_PASSWORD,
        status=UserStatus.ACTIVE,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=email,
        password_hash=password_hash,
        date_of_birth=payload.date_of_birth,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        # Lost a race to the same address. Same answer as any address in use.
        await session.rollback()
        return Accepted()
    code = await _issue_code(session, user, now)
    await session.commit()
    await _send_code(request, user, code)
    return Accepted()


@router.post("/verify-email", response_model=SessionResponse)
async def verify_email(
    payload: VerifyRequest,
    request: Request,
    response: Response,
    session: DatabaseSession,
    auth_service: AuthServiceDependency,
) -> SessionResponse:
    """Exchange the emailed code for a verified account and a session."""

    _closed_unless_enabled()
    email = _normal(str(payload.email))
    identity = _verify_identity(email)
    ip_digest = _digest(f"ip:{client_ip(request)}")
    now = datetime.now(UTC)

    failures_row = (
        await session.execute(
            select(func.count(), func.min(AuthLoginAttempt.occurred_at)).where(
                AuthLoginAttempt.identity_digest == identity,
                AuthLoginAttempt.succeeded.is_(False),
                AuthLoginAttempt.occurred_at >= now - VERIFY_WINDOW,
            )
        )
    ).one()
    if int(failures_row[0] or 0) >= VERIFY_MAX_FAILURES and failures_row[1] is not None:
        raise _too_many(failures_row[1] + VERIFY_WINDOW)

    user = await _individual_by_email(session, email)
    confirmation = None
    if user is not None and user.email_confirmed_at is None:
        confirmation = await session.scalar(
            select(EmailConfirmation)
            .where(
                EmailConfirmation.user_id == user.id,
                EmailConfirmation.confirmed_at.is_(None),
                EmailConfirmation.superseded_at.is_(None),
                EmailConfirmation.expires_at > now,
            )
            .order_by(EmailConfirmation.created_at.desc())
            .limit(1)
        )
    matched = (
        confirmation is not None
        and user is not None
        and secrets.compare_digest(
            confirmation.token_digest,
            _code_digest(confirmation.id, payload.code),
        )
    )
    if not matched:
        session.add(
            AuthLoginAttempt(
                identity_digest=identity,
                ip_digest=ip_digest,
                succeeded=False,
                occurred_at=now,
            )
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "verification_code_invalid",
                "message": "That code is not right or has run out. Ask for a new one.",
            },
        )

    assert user is not None and confirmation is not None
    confirmation.confirmed_at = now
    user.email_confirmed_at = now
    await session.commit()
    try:
        issued = await auth_service.issue_for_provisioned_user(user.id)
    except AuthError as error:
        raise public_auth_error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse.from_issued(issued)


@router.post(
    "/verify-email/resend", response_model=Accepted, status_code=status.HTTP_202_ACCEPTED
)
async def resend_verification(
    payload: VerificationResendRequest,
    request: Request,
    session: DatabaseSession,
) -> Accepted:
    """Send a fresh code.

    Always 202: for an unknown address, an already-verified one, and one the
    mail limiter is holding. A 429 only for known addresses would say which
    addresses are registered; the app keeps its own countdown instead.
    """

    _closed_unless_enabled()
    email = _normal(str(payload.email))
    user = await _individual_by_email(session, email)
    if user is None or user.email_confirmed_at is not None:
        return Accepted()
    now = datetime.now(UTC)
    if await _mail_pause(session, user.id, now) is not None:
        return Accepted()
    code = await _issue_code(session, user, now)
    await session.commit()
    await _send_code(request, user, code)
    return Accepted()


@router.get("/me", response_model=WhoAmI, response_model_exclude_none=True)
async def who_am_i(principal: PrincipalDependency, session: DatabaseSession) -> WhoAmI:
    """Who am I, which kind of account, and whether the address is proven."""

    user = await session.get(User, principal.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    individual = user.account_type == AccountType.INDIVIDUAL.value
    return WhoAmI(
        user_id=user.id,
        account_type="individual" if individual else "school",
        role=user.role.value,
        email=user.email,
        email_verified=user.email_confirmed_at is not None,
        first_name=user.first_name,
        last_name=user.last_name,
        school_id=None if individual else user.school_id,
        consent=(await _consent(session, user)) if individual else None,
    )
