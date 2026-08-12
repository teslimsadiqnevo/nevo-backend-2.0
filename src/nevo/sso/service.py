from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from nevo.auth.entities import AuthUser, IssuedSession, SessionDraft
from nevo.auth.policies import idle_timeout_for_role, requires_single_session
from nevo.auth.ports import AuthAuditLog, SessionRepository, TokenService
from nevo.domain.accounts.vocabulary import (
    SsoConnectionStatus,
    SsoFirstUseDestination,
    SsoProvider,
)
from nevo.sso.entities import (
    RosterSyncBatch,
    RosterSyncHistory,
    RosterSyncResult,
    SsoConnectionHealth,
    SsoDataFlowCategory,
    SsoDisconnection,
    SsoLoginResult,
    SsoProviderIdentity,
    SsoReauthorisation,
    SsoSchoolConfig,
    SsoStart,
)

DEFAULT_SYNC_HISTORY_WINDOW_DAYS = 30
MAX_SYNC_HISTORY_WINDOW_DAYS = 365


class SsoDisconnectedError(Exception):
    """Raised when an action needs a connection the school switched off."""

# What actually crosses the boundary from the identity provider, written for a
# school administrator rather than an engineer. Kept beside the roster sync so
# the notice cannot drift from the code that reads the directory.
SSO_DATA_FLOW: tuple[SsoDataFlowCategory, ...] = (
    SsoDataFlowCategory(
        key="student_directory",
        description=(
            "Student names, school email addresses, and class membership."
        ),
        purpose=(
            "So students can sign in with their school account and appear in "
            "the right class without anyone typing them in."
        ),
    ),
    SsoDataFlowCategory(
        key="teacher_directory",
        description="Teacher names, school email addresses, and classes.",
        purpose=(
            "So teachers can sign in with their school account and see the "
            "classes they teach."
        ),
    ),
    SsoDataFlowCategory(
        key="sign_in_confirmation",
        description=(
            "Confirmation from your provider that a sign-in was genuine."
        ),
        purpose=(
            "So Nevo never has to store or check a password for your staff "
            "or students."
        ),
    ),
)


class SsoRepository(Protocol):
    async def config_for_slug(
        self,
        *,
        school_slug: str,
        provider: SsoProvider,
    ) -> SsoSchoolConfig | None: ...

    async def config_for_school(
        self,
        school_id: UUID,
    ) -> SsoSchoolConfig | None: ...

    async def connection_health(
        self,
        school_id: UUID,
    ) -> SsoConnectionHealth | None: ...

    async def sync_history(
        self,
        *,
        school_id: UUID,
        since: datetime,
        window_days: int,
    ) -> RosterSyncHistory: ...

    async def mark_reauthorisation_started(
        self,
        *,
        school_id: UUID,
        provider: SsoProvider,
        started_at: datetime,
    ) -> None: ...

    async def disconnect(
        self,
        *,
        school_id: UUID,
        provider: SsoProvider,
        disconnected_at: datetime,
        disconnected_by_user_id: UUID,
    ) -> SsoDisconnection | None: ...

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
        triggered_by_user_id: UUID | None = None,
    ) -> RosterSyncResult: ...

    async def record_failed_roster_sync(
        self,
        *,
        school_id: UUID,
        provider: SsoProvider,
        failure_reason: str,
        triggered_by_user_id: UUID | None,
        failed_at: datetime,
    ) -> None: ...


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

    async def connection_health(self, school_id: UUID) -> SsoConnectionHealth:
        """Health card for the admin dashboard.

        Reports rather than probes: checking the provider on every dashboard
        render would put a third-party call on a page load. The stored status
        is written when a real provider interaction succeeds or fails.
        """
        health = await self._repository.connection_health(school_id)
        if health is None:
            raise LookupError("SSO is not configured for this school")
        return replace(
            health,
            school_entry_url=self.school_entry_url(health.school_url_slug),
            data_flow=SSO_DATA_FLOW,
        )

    async def sync_history(
        self,
        *,
        school_id: UUID,
        window_days: int = DEFAULT_SYNC_HISTORY_WINDOW_DAYS,
    ) -> RosterSyncHistory:
        if window_days < 1 or window_days > MAX_SYNC_HISTORY_WINDOW_DAYS:
            raise ValueError(
                "Sync history window must be between 1 and "
                f"{MAX_SYNC_HISTORY_WINDOW_DAYS} days"
            )
        return await self._repository.sync_history(
            school_id=school_id,
            since=self._now() - timedelta(days=window_days),
            window_days=window_days,
        )

    async def sync_roster_for_school(
        self,
        *,
        school_id: UUID,
        triggered_by_user_id: UUID,
    ) -> RosterSyncResult:
        """Manual sync from the admin dashboard, in the actor's own school.

        A provider failure is recorded as a failed run rather than vanishing,
        so the health card can explain what happened and what to do about it.
        """
        config = await self._require_school_config(school_id)
        # Disconnecting was deliberate. Pulling the directory anyway would
        # quietly contradict it; reauthorise is the way back.
        health = await self._repository.connection_health(school_id)
        if health is not None and (
            health.status is SsoConnectionStatus.DISCONNECTED
        ):
            raise SsoDisconnectedError(
                "Single sign-on is disconnected for this school. Reconnect "
                "it before syncing your roster."
            )
        try:
            batch = await self._provider(config.provider).roster_for_school(
                config=config,
            )
        except LookupError as error:
            await self._repository.record_failed_roster_sync(
                school_id=school_id,
                provider=config.provider,
                failure_reason=str(error),
                triggered_by_user_id=triggered_by_user_id,
                failed_at=self._now(),
            )
            raise
        return await self._repository.record_roster_sync(
            school_id=school_id,
            provider=config.provider,
            batch=batch,
            triggered_by_user_id=triggered_by_user_id,
        )

    async def reauthorise(self, school_id: UUID) -> SsoReauthorisation:
        """Recovery path when provider credentials lapse.

        Same OAuth exchange as first setup; the difference is framing, so the
        admin is not made to feel they are starting over.
        """
        config = await self._require_school_config(school_id)
        now = self._now()
        authorization_url = self._provider(config.provider).authorization_url(
            config=config,
            redirect_uri=self._redirect_uri(config.provider),
            state=f"{config.school_url_slug}:{config.provider.value}",
        )
        await self._repository.mark_reauthorisation_started(
            school_id=school_id,
            provider=config.provider,
            started_at=now,
        )
        return SsoReauthorisation(
            provider=config.provider,
            authorization_url=authorization_url,
            school_entry_url=self.school_entry_url(config.school_url_slug),
        )

    async def disconnect(
        self,
        *,
        school_id: UUID,
        disconnected_by_user_id: UUID,
    ) -> SsoDisconnection:
        """Soft disable. No account is deleted and no data is removed."""
        config = await self._require_school_config(school_id)
        disconnection = await self._repository.disconnect(
            school_id=school_id,
            provider=config.provider,
            disconnected_at=self._now(),
            disconnected_by_user_id=disconnected_by_user_id,
        )
        if disconnection is None:
            raise LookupError("SSO is not configured for this school")
        return disconnection

    def school_entry_url(self, school_slug: str) -> str:
        return f"{self._school_base_url}/{school_slug}"

    async def _require_school_config(self, school_id: UUID) -> SsoSchoolConfig:
        config = await self._repository.config_for_school(school_id)
        if config is None:
            raise LookupError("SSO is not configured for this school")
        return config

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
