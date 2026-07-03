from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.auth.ports import CredentialHasher
from nevo.permissions.repositories import SqlAlchemyPermissionRepository
from nevo.permissions.security import HmacInvitationTokenService
from nevo.permissions.service import PermissionService


def build_permission_service(
    sessions: async_sessionmaker[AsyncSession],
    *,
    credential_hasher: CredentialHasher,
    session_pepper: str,
) -> PermissionService:
    return PermissionService(
        repository=SqlAlchemyPermissionRepository(sessions),
        invitation_tokens=HmacInvitationTokenService(session_pepper),
        password_hasher=credential_hasher,
    )
