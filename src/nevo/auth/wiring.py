from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.auth.config import AuthSettings
from nevo.auth.ports import CredentialHasher
from nevo.auth.repositories import (
    SqlAlchemyAuthAuditLog,
    SqlAlchemyLoginRateLimiter,
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)
from nevo.auth.security import Argon2idCredentialHasher, HmacTokenService
from nevo.auth.service import AuthService


def build_credential_hasher(settings: AuthSettings) -> Argon2idCredentialHasher:
    return Argon2idCredentialHasher(
        password_pepper=settings.auth_password_pepper.get_secret_value(),
        pin_pepper=settings.auth_pin_pepper.get_secret_value(),
    )


def build_auth_service(
    sessions: async_sessionmaker[AsyncSession],
    settings: AuthSettings,
    *,
    credential_hasher: CredentialHasher | None = None,
) -> AuthService:
    hasher = credential_hasher or build_credential_hasher(settings)
    return AuthService(
        users=SqlAlchemyUserRepository(sessions),
        sessions=SqlAlchemySessionRepository(sessions),
        rate_limiter=SqlAlchemyLoginRateLimiter(sessions),
        audit_log=SqlAlchemyAuthAuditLog(sessions),
        credential_hasher=hasher,
        token_service=HmacTokenService(
            settings.auth_session_pepper.get_secret_value()
        ),
    )
