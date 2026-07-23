from datetime import UTC, datetime
from uuid import UUID

import pytest

from nevo.auth.entities import AuthUser
from nevo.domain.accounts.vocabulary import (
    RosterSyncStatus,
    SsoFirstUseDestination,
    SsoProvider,
    UserRole,
)
from nevo.sso.entities import (
    RosterAccount,
    RosterSyncBatch,
    RosterSyncResult,
    SsoProviderIdentity,
    SsoSchoolConfig,
)
from nevo.sso.service import SsoService

SCHOOL_ID = UUID("00000000-0000-4000-8000-000000000001")
USER_ID = UUID("00000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("00000000-0000-4000-8000-000000000003")
ISSUE_ID = UUID("00000000-0000-4000-8000-000000000004")


class FakeRepository:
    def __init__(self, *, profile_exists: bool = False) -> None:
        self.profile_exists = profile_exists
        self.roster_batch = None

    async def config_for_slug(self, *, school_slug, provider):
        assert school_slug == "nevo-school"
        return SsoSchoolConfig(
            school_id=SCHOOL_ID,
            school_url_slug=school_slug,
            provider=provider,
            client_id="client-id",
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

    async def record_roster_sync(self, *, school_id, provider, batch):
        self.roster_batch = batch
        return RosterSyncResult(
            status=RosterSyncStatus.PARTIAL_MANUAL_REVIEW,
            imported_students=len(batch.students),
            imported_teachers=len(batch.teachers),
            missing_teacher_class_mappings=1,
            issue_ids=(ISSUE_ID,),
        )


class FakeProviderClient:
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


def service(profile_exists: bool = False) -> tuple[SsoService, FakeRepository]:
    repository = FakeRepository(profile_exists=profile_exists)
    return (
        SsoService(
            repository=repository,
            sessions=FakeSessionRepository(),  # type: ignore[arg-type]
            audit_log=FakeAuditLog(),  # type: ignore[arg-type]
            token_service=FakeTokenService(),  # type: ignore[arg-type]
            provider_clients={SsoProvider.GOOGLE: FakeProviderClient()},
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
