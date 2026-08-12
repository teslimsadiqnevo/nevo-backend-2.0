from datetime import UTC, datetime
from uuid import UUID

import pytest

from nevo.auth.entities import AuthUser
from nevo.domain.accounts.vocabulary import (
    RosterSyncStatus,
    SsoConnectionStatus,
    SsoFirstUseDestination,
    SsoProvider,
    UserRole,
)
from nevo.sso.entities import (
    RosterAccount,
    RosterSyncBatch,
    RosterSyncHistory,
    RosterSyncResult,
    SsoConnectionHealth,
    SsoDisconnection,
    SsoProviderIdentity,
    SsoSchoolConfig,
)
from nevo.sso.service import SSO_DATA_FLOW, SsoDisconnectedError, SsoService

SCHOOL_ID = UUID("00000000-0000-4000-8000-000000000001")
USER_ID = UUID("00000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("00000000-0000-4000-8000-000000000003")
ISSUE_ID = UUID("00000000-0000-4000-8000-000000000004")


class FakeRepository:
    def __init__(
        self,
        *,
        profile_exists: bool = False,
        configured: bool = True,
    ) -> None:
        self.profile_exists = profile_exists
        self.configured = configured
        self.status = SsoConnectionStatus.NEEDS_ATTENTION
        self.roster_batch = None
        self.triggered_by_user_id: UUID | None = None
        self.failures: list[dict] = []
        self.reauthorisations: list[dict] = []
        self.disconnections: list[dict] = []
        self.history_window: tuple[datetime, int] | None = None

    def _config(self) -> SsoSchoolConfig:
        return SsoSchoolConfig(
            school_id=SCHOOL_ID,
            school_url_slug="nevo-school",
            provider=SsoProvider.GOOGLE,
            client_id="client-id",
        )

    async def config_for_slug(self, *, school_slug, provider):
        assert school_slug == "nevo-school"
        return SsoSchoolConfig(
            school_id=SCHOOL_ID,
            school_url_slug=school_slug,
            provider=provider,
            client_id="client-id",
        )

    async def config_for_school(self, school_id):
        assert school_id == SCHOOL_ID
        return self._config() if self.configured else None

    async def connection_health(self, school_id):
        assert school_id == SCHOOL_ID
        if not self.configured:
            return None
        return SsoConnectionHealth(
            school_id=school_id,
            provider=SsoProvider.GOOGLE,
            status=self.status,
            school_url_slug="nevo-school",
            school_entry_url="",
            data_flow=(),
            last_connection_error="Directory permission was withdrawn.",
            connection_checked_at=None,
            reauthorised_at=None,
            last_successful_sync_at=None,
            next_scheduled_sync_at=None,
            disconnected_at=None,
        )

    async def sync_history(self, *, school_id, since, window_days):
        assert school_id == SCHOOL_ID
        self.history_window = (since, window_days)
        return RosterSyncHistory(
            school_id=school_id,
            window_days=window_days,
            successful_runs=2,
            failed_runs=1,
            runs=(),
        )

    async def mark_reauthorisation_started(
        self,
        *,
        school_id,
        provider,
        started_at,
    ):
        self.reauthorisations.append(
            {
                "school_id": school_id,
                "provider": provider,
                "started_at": started_at,
            }
        )

    async def disconnect(
        self,
        *,
        school_id,
        provider,
        disconnected_at,
        disconnected_by_user_id,
    ):
        self.disconnections.append(
            {
                "school_id": school_id,
                "provider": provider,
                "disconnected_by_user_id": disconnected_by_user_id,
            }
        )
        return SsoDisconnection(
            school_id=school_id,
            provider=provider,
            disconnected_at=disconnected_at,
            retained_user_count=42,
        )

    async def record_failed_roster_sync(
        self,
        *,
        school_id,
        provider,
        failure_reason,
        triggered_by_user_id,
        failed_at,
    ):
        self.failures.append(
            {
                "school_id": school_id,
                "provider": provider,
                "failure_reason": failure_reason,
                "triggered_by_user_id": triggered_by_user_id,
            }
        )

    async def upsert_sso_user(self, *, school_id, identity):
        assert school_id == SCHOOL_ID
        assert identity.external_id == "external-1"
        return AuthUser(
            id=USER_ID,
            school_id=school_id,
            role=identity.role.value,
            auth_method="sso",
            status="active",
            email=identity.email,
        )

    async def learner_profile_exists(self, user_id):
        assert user_id == USER_ID
        return self.profile_exists

    async def record_roster_sync(
        self,
        *,
        school_id,
        provider,
        batch,
        triggered_by_user_id=None,
    ):
        self.roster_batch = batch
        self.triggered_by_user_id = triggered_by_user_id
        return RosterSyncResult(
            status=RosterSyncStatus.PARTIAL_MANUAL_REVIEW,
            imported_students=len(batch.students),
            imported_teachers=len(batch.teachers),
            missing_teacher_class_mappings=1,
            issue_ids=(ISSUE_ID,),
        )


class FakeProviderClient:
    def __init__(self, *, roster_fails: bool = False) -> None:
        self.roster_fails = roster_fails

    def authorization_url(self, *, config, redirect_uri, state):
        return f"https://provider.example/auth?state={state}&redirect={redirect_uri}"

    async def identity_from_callback(self, *, config, code, redirect_uri):
        assert code == "auth-code"
        return SsoProviderIdentity(
            provider=config.provider,
            external_id="external-1",
            email="student@example.com",
            first_name="Ada",
            last_name="Student",
            role=UserRole.STUDENT,
        )

    async def roster_for_school(self, *, config):
        if self.roster_fails:
            raise LookupError(
                "Nevo no longer has permission to read your directory. "
                "Reauthorise to restore the connection."
            )
        return RosterSyncBatch(
            students=(
                RosterAccount(
                    external_id="student-1",
                    email="student@example.com",
                    first_name="Ada",
                    last_name="Student",
                    role=UserRole.STUDENT,
                ),
            ),
            teachers=(
                RosterAccount(
                    external_id="teacher-1",
                    email="teacher@example.com",
                    first_name="Theo",
                    last_name="Teacher",
                    role=UserRole.TEACHER,
                    class_external_ids=("missing-class",),
                ),
            ),
        )


class FakeSessionRepository:
    async def create(self, draft, *, replace_active):
        self.draft = draft
        self.replace_active = replace_active
        return None


class FakeAuditLog:
    async def record(self, *args, **kwargs):
        self.recorded = (args, kwargs)


class FakeTokenService:
    def issue(self):
        return "token", "digest"

    def digest(self, token):
        return token

    def protect_identifier(self, value):
        return value


def service(
    profile_exists: bool = False,
    *,
    configured: bool = True,
    roster_fails: bool = False,
) -> tuple[SsoService, FakeRepository]:
    repository = FakeRepository(
        profile_exists=profile_exists,
        configured=configured,
    )
    return (
        SsoService(
            repository=repository,
            sessions=FakeSessionRepository(),  # type: ignore[arg-type]
            audit_log=FakeAuditLog(),  # type: ignore[arg-type]
            token_service=FakeTokenService(),  # type: ignore[arg-type]
            provider_clients={
                SsoProvider.GOOGLE: FakeProviderClient(
                    roster_fails=roster_fails,
                ),
            },
            public_base_url="https://api.nevo.app",
            school_base_url="https://nevo.app",
            now=lambda: datetime(2026, 7, 23, tzinfo=UTC),
        ),
        repository,
    )


@pytest.mark.asyncio
async def test_sso_start_returns_provider_and_school_urls() -> None:
    sso, _ = service()

    start = await sso.start(school_slug="nevo-school", provider=SsoProvider.GOOGLE)

    assert "state=nevo-school:google" in start.authorization_url
    assert start.school_entry_url == "https://nevo.app/nevo-school"


@pytest.mark.asyncio
async def test_sso_callback_routes_first_use_student_to_observed_sequence() -> None:
    sso, _ = service(profile_exists=False)

    result = await sso.callback(
        school_slug="nevo-school",
        provider=SsoProvider.GOOGLE,
        code="auth-code",
    )

    assert result.session.access_token == "token"
    assert result.destination is SsoFirstUseDestination.OBSERVED_INTERACTION


@pytest.mark.asyncio
async def test_roster_sync_reports_missing_teacher_class_mapping() -> None:
    sso, repository = service()

    result = await sso.sync_roster(
        school_slug="nevo-school",
        provider=SsoProvider.GOOGLE,
    )

    assert result.status is RosterSyncStatus.PARTIAL_MANUAL_REVIEW
    assert result.missing_teacher_class_mappings == 1
    assert repository.roster_batch is not None


@pytest.mark.asyncio
async def test_connection_health_is_composed_with_urls_and_data_flow() -> None:
    sso, _ = service()

    health = await sso.connection_health(SCHOOL_ID)

    assert health.status is SsoConnectionStatus.NEEDS_ATTENTION
    assert health.school_entry_url == "https://nevo.app/nevo-school"
    assert health.data_flow == SSO_DATA_FLOW
    assert health.last_connection_error is not None


@pytest.mark.asyncio
async def test_connection_health_is_missing_when_sso_is_not_configured() -> None:
    sso, _ = service(configured=False)

    with pytest.raises(LookupError):
        await sso.connection_health(SCHOOL_ID)


@pytest.mark.asyncio
async def test_sync_history_defaults_to_a_thirty_day_window() -> None:
    sso, repository = service()

    history = await sso.sync_history(school_id=SCHOOL_ID)

    assert history.window_days == 30
    assert repository.history_window is not None
    since, window_days = repository.history_window
    assert window_days == 30
    assert since == datetime(2026, 6, 23, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize("window_days", [0, -1, 366])
async def test_sync_history_rejects_an_out_of_range_window(
    window_days: int,
) -> None:
    sso, _ = service()

    with pytest.raises(ValueError):
        await sso.sync_history(school_id=SCHOOL_ID, window_days=window_days)


@pytest.mark.asyncio
async def test_manual_sync_is_attributed_to_the_administrator() -> None:
    sso, repository = service()

    await sso.sync_roster_for_school(
        school_id=SCHOOL_ID,
        triggered_by_user_id=USER_ID,
    )

    assert repository.triggered_by_user_id == USER_ID


@pytest.mark.asyncio
async def test_manual_sync_records_a_provider_failure_before_raising() -> None:
    """A failure the admin can see beats one that vanishes."""
    sso, repository = service(roster_fails=True)

    with pytest.raises(LookupError):
        await sso.sync_roster_for_school(
            school_id=SCHOOL_ID,
            triggered_by_user_id=USER_ID,
        )

    assert len(repository.failures) == 1
    assert repository.failures[0]["triggered_by_user_id"] == USER_ID
    assert "permission" in repository.failures[0]["failure_reason"]


@pytest.mark.asyncio
async def test_manual_sync_refuses_while_disconnected() -> None:
    """Disconnecting was deliberate; syncing anyway would contradict it."""
    sso, repository = service()
    repository.status = SsoConnectionStatus.DISCONNECTED

    with pytest.raises(SsoDisconnectedError):
        await sso.sync_roster_for_school(
            school_id=SCHOOL_ID,
            triggered_by_user_id=USER_ID,
        )

    assert repository.roster_batch is None


@pytest.mark.asyncio
async def test_reauthorise_returns_a_fresh_provider_url() -> None:
    sso, repository = service()

    reauthorisation = await sso.reauthorise(SCHOOL_ID)

    assert "state=nevo-school:google" in reauthorisation.authorization_url
    assert reauthorisation.school_entry_url == "https://nevo.app/nevo-school"
    assert len(repository.reauthorisations) == 1


@pytest.mark.asyncio
async def test_disconnect_keeps_accounts_and_reports_the_count() -> None:
    sso, repository = service()

    disconnection = await sso.disconnect(
        school_id=SCHOOL_ID,
        disconnected_by_user_id=USER_ID,
    )

    assert disconnection.retained_user_count == 42
    assert repository.disconnections[0]["disconnected_by_user_id"] == USER_ID


@pytest.mark.asyncio
async def test_admin_actions_report_when_sso_is_not_configured() -> None:
    sso, _ = service(configured=False)

    for action in (
        sso.reauthorise(SCHOOL_ID),
        sso.sync_roster_for_school(
            school_id=SCHOOL_ID,
            triggered_by_user_id=USER_ID,
        ),
        sso.disconnect(
            school_id=SCHOOL_ID,
            disconnected_by_user_id=USER_ID,
        ),
    ):
        with pytest.raises(LookupError):
            await action


def test_data_flow_notice_explains_purpose_in_plain_language() -> None:
    assert len(SSO_DATA_FLOW) >= 3
    for category in SSO_DATA_FLOW:
        assert category.description.endswith(".")
        assert category.purpose.startswith("So ")
        # The notice is read by a non-technical administrator.
        for jargon in ("oauth", "scope", "token", "api", "endpoint"):
            assert jargon not in category.description.casefold()
            assert jargon not in category.purpose.casefold()
