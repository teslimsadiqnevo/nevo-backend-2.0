from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from nevo.auth.entities import AuthPrincipal, IssuedSession
from nevo.auth.errors import (
    AuthError,
    InvalidSessionError,
    RateLimitExceededError,
)
from nevo.auth.service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
bearer = HTTPBearer(auto_error=False)


class PasswordLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=1_024)


class PinLoginRequest(BaseModel):
    school_code: str = Field(min_length=2, max_length=50)
    login_identifier: str = Field(min_length=1, max_length=50)
    pin: str = Field(pattern=r"^\d{4,8}$")


class SessionResponse(BaseModel):
    access_token: str
    token_type: str
    expires_at: datetime
    user_id: UUID
    role: str
    replaced_session: bool

    @classmethod
    def from_issued(cls, issued: IssuedSession) -> "SessionResponse":
        return cls(
            access_token=issued.access_token,
            token_type=issued.token_type,
            expires_at=issued.expires_at,
            user_id=issued.user_id,
            role=issued.role,
            replaced_session=issued.replaced_session,
        )


class PrincipalResponse(BaseModel):
    user_id: UUID
    role: str
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


@router.post("/login/password", response_model=SessionResponse)
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


@router.post("/login/pin", response_model=SessionResponse)
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
    return SessionResponse.from_issued(issued)


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


@router.get("/session", response_model=PrincipalResponse)
async def current_session(
    principal: PrincipalDependency,
) -> PrincipalResponse:
    return PrincipalResponse.from_principal(principal)


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
    return request.client.host if request.client else "unknown"
