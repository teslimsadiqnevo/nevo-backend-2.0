from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.auth.entities import AuthUser
from nevo.db.models.account import Class, User
from nevo.db.models.learner_profile import LearnerProfile
from nevo.db.models.sso import (
    RosterSyncIssue,
    RosterSyncRun,
    SchoolSsoConfiguration,
)
from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    RosterSyncStatus,
    SsoProvider,
    UserStatus,
)
from nevo.sso.entities import (
    RosterAccount,
    RosterSyncBatch,
    RosterSyncResult,
    SsoProviderIdentity,
    SsoSchoolConfig,
)


class SqlAlchemySsoRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def config_for_slug(
        self,
        *,
        school_slug: str,
        provider: SsoProvider,
    ) -> SsoSchoolConfig | None:
        async with self._sessions() as session:
            record = await session.scalar(
                select(SchoolSsoConfiguration).where(
                    SchoolSsoConfiguration.school_url_slug == school_slug,
                    SchoolSsoConfiguration.provider == provider,
                    SchoolSsoConfiguration.enabled.is_(True),
                )
            )
        if record is None:
            return None
        return SsoSchoolConfig(
            school_id=record.school_id,
            school_url_slug=record.school_url_slug,
            provider=record.provider,
            client_id=record.client_id,
            tenant_id=record.tenant_id,
            hosted_domain=record.hosted_domain,
        )

    async def upsert_sso_user(
        self,
        *,
        school_id: UUID,
        identity: SsoProviderIdentity,
    ) -> AuthUser:
        async with self._sessions.begin() as session:
            user = await session.scalar(
                select(User).where(
                    User.sso_external_id == _sso_external_id(identity),
                )
            )
            if user is None:
                user = await session.scalar(
                    select(User).where(
                        User.school_id == school_id,
                        func.lower(User.email) == identity.email.casefold(),
                    )
                )
            if user is None:
                user = User(
                    id=uuid4(),
                    school_id=school_id,
                    role=identity.role,
                    auth_method=AuthMethod.SSO,
                    email=identity.email.casefold(),
                    first_name=identity.first_name,
                    last_name=identity.last_name,
                    sso_external_id=_sso_external_id(identity),
                    status=UserStatus.ACTIVE,
                )
                session.add(user)
            else:
                user.auth_method = AuthMethod.SSO
                user.sso_external_id = _sso_external_id(identity)
                user.status = UserStatus.ACTIVE
                user.first_name = identity.first_name
                user.last_name = identity.last_name
                user.email = identity.email.casefold()
            await session.flush()
            return _auth_user(user)

    async def learner_profile_exists(self, user_id: UUID) -> bool:
        async with self._sessions() as session:
            profile_id = await session.scalar(
                select(LearnerProfile.id).where(LearnerProfile.learner_id == user_id)
            )
        return profile_id is not None

    async def record_roster_sync(
        self,
        *,
        school_id: UUID,
        provider: SsoProvider,
        batch: RosterSyncBatch,
    ) -> RosterSyncResult:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            imported_students = 0
            imported_teachers = 0
            missing_mappings = 0
            run = RosterSyncRun(
                id=uuid4(),
                school_id=school_id,
                provider=provider,
                status=RosterSyncStatus.COMPLETED,
                started_at=now,
                completed_at=now,
            )
            session.add(run)
            await session.flush()

            for student in batch.students:
                await _upsert_roster_user(session, school_id, provider, student)
                imported_students += 1
            issue_ids: list[UUID] = []
            for teacher in batch.teachers:
                await _upsert_roster_user(session, school_id, provider, teacher)
                imported_teachers += 1
                for class_external_id in teacher.class_external_ids:
                    class_exists = await session.scalar(
                        select(Class.id).where(
                            Class.school_id == school_id,
                            Class.class_code == class_external_id,
                        )
                    )
                    if class_exists is None:
                        missing_mappings += 1
                        issue = RosterSyncIssue(
                            id=uuid4(),
                            roster_sync_run_id=run.id,
                            school_id=school_id,
                            external_reference=class_external_id,
                            description=(
                                "Teacher-class mapping was not found during "
                                "roster sync and needs manual review."
                            ),
                        )
                        session.add(issue)
                        issue_ids.append(issue.id)
            run.imported_students = imported_students
            run.imported_teachers = imported_teachers
            run.missing_teacher_class_mappings = missing_mappings
            run.status = (
                RosterSyncStatus.PARTIAL_MANUAL_REVIEW
                if missing_mappings
                else RosterSyncStatus.COMPLETED
            )
            await session.flush()
            return RosterSyncResult(
                status=run.status,
                imported_students=imported_students,
                imported_teachers=imported_teachers,
                missing_teacher_class_mappings=missing_mappings,
                issue_ids=tuple(issue_ids),
            )


async def _upsert_roster_user(
    session: AsyncSession,
    school_id: UUID,
    provider: SsoProvider,
    account: RosterAccount,
) -> User:
    external_id = f"{provider.value}:{account.external_id}"
    user = await session.scalar(select(User).where(User.sso_external_id == external_id))
    if user is None:
        user = await session.scalar(
            select(User).where(
                User.school_id == school_id,
                func.lower(User.email) == account.email.casefold(),
            )
        )
    if user is None:
        user = User(
            id=uuid4(),
            school_id=school_id,
            role=account.role,
            auth_method=AuthMethod.SSO,
            email=account.email.casefold(),
            first_name=account.first_name,
            last_name=account.last_name,
            sso_external_id=external_id,
            status=UserStatus.ACTIVE,
        )
        session.add(user)
    else:
        user.auth_method = AuthMethod.SSO
        user.sso_external_id = external_id
        user.status = UserStatus.ACTIVE
        user.first_name = account.first_name
        user.last_name = account.last_name
        user.email = account.email.casefold()
    await session.flush()
    return user


def _sso_external_id(identity: SsoProviderIdentity) -> str:
    return f"{identity.provider.value}:{identity.external_id}"


def _auth_user(user: User) -> AuthUser:
    return AuthUser(
        id=user.id,
        school_id=user.school_id,
        role=user.role.value,
        auth_method=user.auth_method.value,
        status=user.status.value,
        email=user.email,
        password_hash=user.password_hash,
        pin_hash=user.pin_hash,
        login_identifier=user.login_identifier,
        deactivated_at=user.deactivated_at,
    )
