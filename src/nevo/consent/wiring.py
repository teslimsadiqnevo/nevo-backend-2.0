from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.consent.repositories import SqlAlchemyConsentRepository
from nevo.consent.security import HmacConsentTokenService
from nevo.consent.service import ConsentService


def build_consent_service(
    sessions: async_sessionmaker[AsyncSession],
    *,
    token_pepper: str,
    public_base_url: str,
) -> ConsentService:
    return ConsentService(
        repository=SqlAlchemyConsentRepository(sessions),
        token_service=HmacConsentTokenService(token_pepper),
        public_base_url=public_base_url,
    )
