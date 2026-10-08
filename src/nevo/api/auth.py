from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AliasChoices, BaseModel, EmailStr, Field

from nevo.api.casing import CAMEL_CONFIG
from nevo.auth.entities import AuthPrincipal, IssuedSession
from nevo.auth.errors import (
    AuthError,
    InvalidSessionError,
    RateLimitExceededError,
    SchoolCodeRequiredError,
)
from nevo.auth.policies import absolute_lifetime_for_role
from nevo.auth.service import AuthService
from nevo.domain.accounts.vocabulary import UserRole

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
bearer = HTTPBearer(auto_error=False)


class PasswordLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=1_024)


#: A child's PIN, one shape on every door into the product.
#:
#: Every newly chosen or reset PIN is four digits. Six digits remain accepted
#: only at sign-in so an existing learner can unlock once and be asked to
#: replace it; no endpoint can create another legacy PIN.
STUDENT_PIN_MIN_DIGITS = 4
STUDENT_PIN_MAX_DIGITS = 4
LEGACY_STUDENT_PIN_DIGITS = 6
StudentPin = Annotated[
    str,
    Field(
        min_length=STUDENT_PIN_MIN_DIGITS,
        max_length=STUDENT_PIN_MAX_DIGITS,
        pattern=r"^\d+$",
    ),
]
LoginPin = Annotated[
    str,
    Field(
        min_length=STUDENT_PIN_MIN_DIGITS,
        max_length=LEGACY_STUDENT_PIN_DIGITS,
        pattern=r"^(?:\d{4}|\d{6})$",
    ),
]


class PinLoginRequest(BaseModel):
    model_config = CAMEL_CONFIG

    school_code: str = Field(min_length=2, max_length=50)
    #: The child's Student ID / Admission Number. Sent as admissionNumber;
    #: loginIdentifier is still accepted as the older name for the same field,
    #: so a client mid-migration keeps working. SCRUM-202.
    login_identifier: str = Field(
        min_length=1,
        max_length=60,
        validation_alias=AliasChoices("admissionNumber", "loginIdentifier", "login_identifier"),
        serialization_alias="admissionNumber",
    )
    pin: LoginPin


class UnifiedLoginRequest(BaseModel):
    method: str = Field(pattern="^(password|pin)$")
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=1_024)
    school_code: str | None = Field(default=None, alias="schoolCode", max_length=50)
    login_identifier: str | None = Field(
        default=None,
        alias="loginIdentifier",
        max_length=60,
    )
    pin: LoginPin | None = None


class SessionResponse(BaseModel):
    model_config = CAMEL_CONFIG

    access_token: str
    token_type: Literal["bearer"]
    expires_at: datetime
    user_id: UUID
    role: UserRole
    replaced_session: bool
    pin_length: int | None = None
    pin_change_required: bool = False
    absolute_lifetime_hours: int

    @classmethod
    def from_issued(
        cls,
        issued: IssuedSession,
        *,
        pin_length: int | None = None,
        pin_change_required: bool = False,
    ) -> "SessionResponse":
        return cls(
            access_token=issued.access_token,
            token_type="bearer",
            expires_at=issued.expires_at,
            user_id=issued.user_id,
            role=UserRole(issued.role),
            replaced_session=issued.replaced_session,
            pin_length=pin_length,
            pin_change_required=pin_change_required,
            absolute_lifetime_hours=int(
                absolute_lifetime_for_role(issued.role).total_seconds() // 3600
            ),
        )


class PrincipalResponse(BaseModel):
    model_config = CAMEL_CONFIG

    user_id: UUID
    role: UserRole
    session_id: UUID

    @classmethod
    def from_principal(cls, principal: AuthPrincipal) -> "PrincipalResponse":
        return cls(
            user_id=principal.user_id,
            role=principal.role,
            session_id=principal.session_id,
        )


def get_auth_service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if not isinstance(service, AuthService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Authentication is temporarily unavailable.",
            },
        )
    return service


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
BearerDependency = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(bearer),
]


@router.post(
    "/login",
    response_model=SessionResponse,
    responses={
        401: {
            "description": (
                "authentication_failed when the credential is wrong, "
                "account_paused when it is right but the account is not open, "
                "too_many_attempts when rate limited"
            )
        },
    },
)
async def unified_login(
    payload: UnifiedLoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDependency,
) -> SessionResponse:
    try:
        if payload.method == "password":
            if payload.email is None or payload.password is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Email and password are required",
                )
            issued = await service.login_with_password(
                email=str(payload.email),
                password=payload.password,
                ip_address=client_ip(request),
            )
        else:
            if not (payload.school_code and payload.login_identifier and payload.pin):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="School code, login identifier, and PIN are required",
                )
            issued = await service.login_with_pin(
                school_code=payload.school_code,
                login_identifier=payload.login_identifier,
                pin=payload.pin,
                ip_address=client_ip(request),
            )
    except AuthError as error:
        raise public_auth_error(error) from error
    response.headers["Cache-Control"] = "no-store"
    pin_length = len(payload.pin) if payload.method == "pin" and payload.pin else None
    return SessionResponse.from_issued(
        issued,
        pin_length=pin_length,
        pin_change_required=pin_length == LEGACY_STUDENT_PIN_DIGITS,
    )


@router.post(
    "/login/password",
    response_model=SessionResponse,
    responses={
        401: {
            "description": (
                "authentication_failed when the credential is wrong, "
                "account_paused when it is right but the account is not open, "
                "too_many_attempts when rate limited"
            )
        },
    },
)
async def login_with_password(
    payload: PasswordLoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDependency,
) -> SessionResponse:
    try:
        issued = await service.login_with_password(
            email=str(payload.email),
            password=payload.password,
            ip_address=client_ip(request),
        )
    except AuthError as error:
        raise public_auth_error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse.from_issued(issued)


@router.post(
    "/login/pin",
    response_model=SessionResponse,
    responses={
        401: {
            "description": (
                "authentication_failed when the credential is wrong, "
                "account_paused when it is right but the account is not open, "
                "too_many_attempts when rate limited"
            )
        },
    },
)
async def login_with_pin(
    payload: PinLoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDependency,
) -> SessionResponse:
    try:
        issued = await service.login_with_pin(
            school_code=payload.school_code,
            login_identifier=payload.login_identifier,
            pin=payload.pin,
            ip_address=client_ip(request),
        )
    except AuthError as error:
        raise public_auth_error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse.from_issued(
        issued,
        pin_length=len(payload.pin),
        pin_change_required=len(payload.pin) == LEGACY_STUDENT_PIN_DIGITS,
    )


async def authenticated_principal(
    credentials: BearerDependency,
    service: AuthServiceDependency,
) -> AuthPrincipal:
    token = require_bearer_token(credentials)
    try:
        return await service.authenticate(token)
    except AuthError as error:
        raise public_auth_error(error) from error


PrincipalDependency = Annotated[
    AuthPrincipal,
    Depends(authenticated_principal),
]


async def optional_authenticated_principal(
    request: Request,
    service: AuthServiceDependency,
) -> AuthPrincipal | None:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if not token or scheme.casefold() != "bearer":
        return None
    try:
        return await service.authenticate(token)
    except AuthError as error:
        raise public_auth_error(error) from error


OptionalPrincipalDependency = Annotated[
    AuthPrincipal | None,
    Depends(optional_authenticated_principal),
]


@router.get("/session", response_model=PrincipalResponse)
async def current_session(
    principal: PrincipalDependency,
) -> PrincipalResponse:
    return PrincipalResponse.from_principal(principal)


@router.post("/session/refresh", response_model=SessionResponse)
async def refresh_session(
    credentials: BearerDependency,
    service: AuthServiceDependency,
    response: Response,
) -> SessionResponse:
    """Renew an unexpired session and return its new client-side deadline."""
    token = require_bearer_token(credentials)
    try:
        issued = await service.refresh(token)
    except AuthError as error:
        raise public_auth_error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse.from_issued(issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    credentials: BearerDependency,
    service: AuthServiceDependency,
) -> None:
    token = require_bearer_token(credentials)
    await service.logout(token)


def require_bearer_token(
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    if credentials is None:
        raise public_auth_error(InvalidSessionError())
    return credentials.credentials


def public_auth_error(error: AuthError) -> HTTPException:
    status_code = status.HTTP_401_UNAUTHORIZED
    if isinstance(error, RateLimitExceededError):
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
    elif isinstance(error, SchoolCodeRequiredError):
        status_code = status.HTTP_409_CONFLICT
    return HTTPException(
        status_code=status_code,
        detail={
            "code": error.code,
            "message": error.public_message,
        },
        headers={"WWW-Authenticate": "Bearer"}
        if status_code == status.HTTP_401_UNAUTHORIZED
        else None,
    )


def client_ip(request: Request) -> str:
    """The caller's address, as seen from in front of the load balancer.

    ``request.client.host`` is the proxy, and on Render it is a different
    internal address on almost every request - so a rate limit keyed on it
    counted each attempt against a fresh bucket and never fired. Proved
    against production: seven requests from one machine arrived as six
    distinct hosts.

    The first entry of X-Forwarded-For is the caller. The last entry was
    tried first, on the reasoning that a caller cannot choose what our own
    proxy appends - but measured against production it varies too, so it
    bucketed one machine several ways and the limit fired only sometimes.

    The first entry is stable and is therefore the one that works, at the
    cost of being client-supplied and so spoofable. That is a real limit and
    not a hidden one: an IP bucket alone cannot carry a throttle here, which
    is why the entry lookup also throttles on the identity being guessed and
    on the school code being guessed against. Neither of those is in the
    caller's gift.
    """

    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if hops:
        return hops[0]
    return request.client.host if request.client else "unknown"
