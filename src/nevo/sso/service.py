from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from nevo.auth.entities import AuthUser, IssuedSession, SessionDraft
from nevo.auth.policies import idle_timeout_for_role, requires_single_session
from nevo.auth.ports import AuthAuditLog, SessionRepository, TokenService
from nevo.domain.accounts.vocabulary import (
    SsoFirstUseDestination,
    SsoProvider,
)
from nevo.sso.entities import (
    RosterSyncBatch,
    RosterSyncResult,
    SsoLoginResult,
    SsoProviderIdentity,
    SsoSchoolConfig,
    SsoStart,
)


class SsoRepository(Protocol):
    async def config_for_slug(
        self,
        *,
        school_slug: str,
        provider: SsoProvider,
    ) -> SsoSchoolConfig | None: ...

    async def upsert_sso_user(
        self,
        *,
        school_id: UUID,
        identity: SsoProviderIdentity,
    ) -> AuthUser: ...

    async def learner_profile_exists(self, user_id: UUID) -> bool: ...

    async def record_roster_sync(
        self,
        *,
        school_id: UUID,
        provider: SsoProvider,
        batch: RosterSyncBatch,
    ) -> RosterSyncResult: ...


class SsoProviderClient(Protocol):
    def authorization_url(
        self,
        *,
        config: SsoSchoolConfig,
        redirect_uri: str,
        state: str,
    ) -> str: ...

    async def identity_from_callback(
        self,
        *,
        config: SsoSchoolConfig,
        code: str,
        redirect_uri: str,
    ) -> SsoProviderIdentity: ...

    async def roster_for_school(
        self,
        *,
        config: SsoSchoolConfig,
    ) -> RosterSyncBatch: ...


class SsoService:
    def __init__(
        self,
        *,
        repository: SsoRepository,
        sessions: SessionRepository,
        audit_log: AuthAuditLog,
        token_service: TokenService,
        provider_clients: dict[SsoProvider, SsoProviderClient],
        public_base_url: str,
        school_base_url: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._sessions = sessions
        self._audit_log = audit_log
        self._token_service = token_service
        self._provider_clients = provider_clients
        self._public_base_url = public_base_url.rstrip("/")
        self._school_base_url = school_base_url.rstrip("/")
        self._now = now or (lambda: datetime.now(UTC))

    async def start(
        self,
        *,
        school_slug: str,
        provider: SsoProvider,
    ) -> SsoStart:
        config = await self._require_config(school_slug, provider)
        redirect_uri = self._redirect_uri(provider)
        state = f"{config.school_url_slug}:{provider.value}"
        return SsoStart(
            authorization_url=self._provider(provider).authorization_url(
                config=config,
                redirect_uri=redirect_uri,
                state=state,
            ),
            school_entry_url=self.school_entry_url(config.school_url_slug),
        )

    async def callback(
        self,
        *,
        school_slug: str,
        provider: SsoProvider,
        code: str,
    ) -> SsoLoginResult:
        config = await self._require_config(school_slug, provider)
        identity = await self._provider(provider).identity_from_callback(
            config=config,
            code=code,
            redirect_uri=self._redirect_uri(provider),
        )
        user = await self._repository.upsert_sso_user(
            school_id=config.school_id,
            identity=identity,
        )
        session = await self._issue_session(user)
        first_use = not await self._repository.learner_profile_exists(user.id)
        return SsoLoginResult(
            session=session,
            destination=(
                SsoFirstUseDestination.OBSERVED_INTERACTION
                if first_use
                else SsoFirstUseDestination.HOME_DASHBOARD
            ),
        )

    async def sync_roster(
        self,
        *,
        school_slug: str,
        provider: SsoProvider,
    ) -> RosterSyncResult:
        config = await self._require_config(school_slug, provider)
        batch = await self._provider(provider).roster_for_school(config=config)
        return await self._repository.record_roster_sync(
            school_id=config.school_id,
            provider=provider,
            batch=batch,
        )

    def school_entry_url(self, school_slug: str) -> str:
        return f"{self._school_base_url}/{school_slug}"

    async def _issue_session(self, user: AuthUser) -> IssuedSession:
        now = self._now()
        token, token_digest = self._token_service.issue()
        draft = SessionDraft(
            id=uuid4(),
            user_id=user.id,
            role=user.role,
            token_digest=token_digest,
            created_at=now,
            last_seen_at=now,
            expires_at=now + idle_timeout_for_role(user.role),
        )
        replaced = await self._sessions.create(
            draft,
            replace_active=requires_single_session(user.role),
        )
        await self._audit_log.record(
            "sso_login_succeeded",
            occurred_at=now,
            user_id=user.id,
            session_id=draft.id,
            identity_digest=None,
            ip_digest=None,
            details={"method": "sso"},
        )
        return IssuedSession(
            access_token=token,
            token_type="bearer",
            expires_at=draft.expires_at,
            user_id=user.id,
            role=user.role,
            replaced_session=replaced is not None,
        )

    async def _require_config(
        self,
        school_slug: str,
        provider: SsoProvider,
    ) -> SsoSchoolConfig:
        config = await self._repository.config_for_slug(
            school_slug=school_slug,
            provider=provider,
        )
        if config is None:
            raise LookupError("SSO is not configured for this school and provider")
        return config

    def _provider(self, provider: SsoProvider) -> SsoProviderClient:
        try:
            return self._provider_clients[provider]
        except KeyError as error:
            raise LookupError("SSO provider client is not configured") from error

    def _redirect_uri(self, provider: SsoProvider) -> str:
        return f"{self._public_base_url}/api/v1/auth/sso/{provider.value}/callback"


class UnavailableSsoProviderClient:
    def authorization_url(
        self,
        *,
        config: SsoSchoolConfig,
        redirect_uri: str,
        state: str,
    ) -> str:
        del config, redirect_uri, state
        raise LookupError("SSO provider client is not configured")

    async def identity_from_callback(
        self,
        *,
        config: SsoSchoolConfig,
        code: str,
        redirect_uri: str,
    ) -> SsoProviderIdentity:
        del config, code, redirect_uri
        raise LookupError("SSO provider client is not configured")

    async def roster_for_school(
        self,
        *,
        config: SsoSchoolConfig,
    ) -> RosterSyncBatch:
        del config
        raise LookupError("Roster provider client is not configured")
