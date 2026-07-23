from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.auth.config import AuthSettings
from nevo.auth.repositories import SqlAlchemyAuthAuditLog, SqlAlchemySessionRepository
from nevo.auth.security import HmacTokenService
from nevo.domain.accounts.vocabulary import SsoProvider
from nevo.sso.config import SsoSettings
from nevo.sso.providers import GoogleSsoProviderClient, MicrosoftSsoProviderClient
from nevo.sso.repositories import SqlAlchemySsoRepository
from nevo.sso.service import SsoService


def build_sso_service(
    sessions: async_sessionmaker[AsyncSession],
    auth_settings: AuthSettings,
    sso_settings: SsoSettings,
) -> SsoService:
    return SsoService(
        repository=SqlAlchemySsoRepository(sessions),
        sessions=SqlAlchemySessionRepository(sessions),
        audit_log=SqlAlchemyAuthAuditLog(sessions),
        token_service=HmacTokenService(
            auth_settings.auth_session_pepper.get_secret_value()
        ),
        provider_clients={
            SsoProvider.MICROSOFT: MicrosoftSsoProviderClient(
                client_secret=(
                    sso_settings.microsoft_client_secret.get_secret_value()
                    if sso_settings.microsoft_client_secret is not None
                    else None
                )
            ),
            SsoProvider.GOOGLE: GoogleSsoProviderClient(
                client_secret=(
                    sso_settings.google_client_secret.get_secret_value()
                    if sso_settings.google_client_secret is not None
                    else None
                )
            ),
        },
        public_base_url=str(sso_settings.public_base_url),
        school_base_url=str(sso_settings.school_base_url),
    )
