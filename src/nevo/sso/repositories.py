from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.auth.entities import AuthUser
from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.learner_profile import LearnerProfile
from nevo.db.models.sso import (
    RosterSyncIssue,
    RosterSyncRun,
    SchoolSsoConfiguration,
)
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    RosterSyncStatus,
    SsoConnectionStatus,
    SsoProvider,
    UserStatus,
)
from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)
from nevo.sso.entities import (
    RosterAccount,
    RosterSyncBatch,
    RosterSyncHistory,
    RosterSyncIssueView,
    RosterSyncResult,
    RosterSyncRunView,
    SsoConnectionHealth,
    SsoDisconnection,
    SsoProviderIdentity,
    SsoSchoolConfig,
)

# Shown verbatim to a non-technical administrator, so it names the action
# rather than the cause.
MISSING_CLASS_RESOLUTION_HINT = (
    "Nevo could not find a matching class for this code. Check the class "
    "exists in Nevo with the same code as in your directory, or assign the "
    "teacher to the class by hand from the class page."
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
        return _school_config(record)

    async def config_for_school(
        self,
        school_id: UUID,
    ) -> SsoSchoolConfig | None:
        async with self._sessions() as session:
            record = await session.scalar(
                select(SchoolSsoConfiguration)
                .where(SchoolSsoConfiguration.school_id == school_id)
                .order_by(SchoolSsoConfiguration.created_at)
            )
        if record is None:
            return None
        return _school_config(record)

    async def connection_health(
        self,
        school_id: UUID,
    ) -> SsoConnectionHealth | None:
        async with self._sessions() as session:
            record = await session.scalar(
                select(SchoolSsoConfiguration)
                .where(SchoolSsoConfiguration.school_id == school_id)
                .order_by(SchoolSsoConfiguration.created_at)
            )
            if record is None:
                return None
            # Derived rather than denormalised: a stored copy would drift the
            # moment a sync is written by any other path.
            last_successful_sync_at = await session.scalar(
                select(func.max(RosterSyncRun.completed_at)).where(
                    RosterSyncRun.school_id == school_id,
                    RosterSyncRun.status != RosterSyncStatus.FAILED,
                )
            )
        return SsoConnectionHealth(
            school_id=record.school_id,
            provider=record.provider,
            status=record.connection_status,
            school_url_slug=record.school_url_slug,
            school_entry_url="",
            data_flow=(),
            last_connection_error=record.last_connection_error,
            connection_checked_at=record.connection_checked_at,
            reauthorised_at=record.reauthorised_at,
            last_successful_sync_at=last_successful_sync_at,
            next_scheduled_sync_at=record.next_scheduled_sync_at,
            disconnected_at=record.disconnected_at,
        )

    async def sync_history(
        self,
        *,
        school_id: UUID,
        since: datetime,
        window_days: int,
    ) -> RosterSyncHistory:
        async with self._sessions() as session:
            runs = list(
                await session.scalars(
                    select(RosterSyncRun)
                    .where(
                        RosterSyncRun.school_id == school_id,
                        RosterSyncRun.started_at >= since,
                    )
                    .order_by(RosterSyncRun.started_at.desc())
                )
            )
            issues_by_run: dict[UUID, list[RosterSyncIssue]] = {}
            if runs:
                issues = await session.scalars(
                    select(RosterSyncIssue)
                    .where(
                        RosterSyncIssue.roster_sync_run_id.in_(
                            [run.id for run in runs]
                        )
                    )
                    .order_by(RosterSyncIssue.created_at)
                )
                for issue in issues:
                    issues_by_run.setdefault(
                        issue.roster_sync_run_id, []
                    ).append(issue)

        return RosterSyncHistory(
            school_id=school_id,
            window_days=window_days,
            successful_runs=sum(
                1 for run in runs if run.status is not RosterSyncStatus.FAILED
            ),
            failed_runs=sum(
                1 for run in runs if run.status is RosterSyncStatus.FAILED
            ),
            runs=tuple(
                RosterSyncRunView(
                    id=run.id,
                    provider=run.provider,
                    status=run.status,
                    imported_students=run.imported_students,
                    imported_teachers=run.imported_teachers,
                    missing_teacher_class_mappings=(
                        run.missing_teacher_class_mappings
                    ),
                    failure_reason=run.failure_reason,
                    triggered_manually=run.triggered_manually,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    issues=tuple(
                        RosterSyncIssueView(
                            id=issue.id,
                            external_reference=issue.external_reference,
                            description=issue.description,
                            resolution_hint=issue.resolution_hint,
                        )
                        for issue in issues_by_run.get(run.id, ())
                    ),
                )
                for run in runs
            ),
        )

    async def mark_reauthorisation_started(
        self,
        *,
        school_id: UUID,
        provider: SsoProvider,
        started_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(SchoolSsoConfiguration)
                .where(
                    SchoolSsoConfiguration.school_id == school_id,
                    SchoolSsoConfiguration.provider == provider,
                )
                .values(connection_checked_at=started_at)
            )

    async def disconnect(
        self,
        *,
        school_id: UUID,
        provider: SsoProvider,
        disconnected_at: datetime,
        disconnected_by_user_id: UUID,
    ) -> SsoDisconnection | None:
        async with self._sessions.begin() as session:
            record = await session.scalar(
                select(SchoolSsoConfiguration)
                .where(
                    SchoolSsoConfiguration.school_id == school_id,
                    SchoolSsoConfiguration.provider == provider,
                )
                .with_for_update()
            )
            if record is None:
                return None
            record.enabled = False
            record.connection_status = SsoConnectionStatus.DISCONNECTED
            record.disconnected_at = disconnected_at
            record.disconnected_by_user_id = disconnected_by_user_id
            record.next_scheduled_sync_at = None
            # Accounts are deliberately untouched: no deactivation, no
            # deletion. Counted so the confirmation can state the real number.
            retained_user_count = await session.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.school_id == school_id,
                    User.auth_method == AuthMethod.SSO,
                )
            )
            await session.flush()
            return SsoDisconnection(
                school_id=school_id,
                provider=provider,
                disconnected_at=disconnected_at,
                retained_user_count=int(retained_user_count or 0),
            )

    async def record_failed_roster_sync(
        self,
        *,
        school_id: UUID,
        provider: SsoProvider,
        failure_reason: str,
        triggered_by_user_id: UUID | None,
        failed_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            session.add(
                RosterSyncRun(
                    id=uuid4(),
                    school_id=school_id,
                    provider=provider,
                    status=RosterSyncStatus.FAILED,
                    failure_reason=failure_reason,
                    triggered_manually=triggered_by_user_id is not None,
                    triggered_by_user_id=triggered_by_user_id,
                    started_at=failed_at,
                    completed_at=failed_at,
                )
            )
            # A provider refusal is the signal that credentials lapsed, so the
            # health card starts telling the truth immediately.
            await session.execute(
                update(SchoolSsoConfiguration)
                .where(
                    SchoolSsoConfiguration.school_id == school_id,
                    SchoolSsoConfiguration.provider == provider,
                    SchoolSsoConfiguration.connection_status
                    != SsoConnectionStatus.DISCONNECTED,
                )
                .values(
                    connection_status=SsoConnectionStatus.NEEDS_ATTENTION,
                    last_connection_error=failure_reason,
                    connection_checked_at=failed_at,
                )
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

    async def save_provider_credential(
        self,
        *,
        school_id: UUID,
        provider: SsoProvider,
        ciphertext: str,
    ) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(SchoolSsoConfiguration)
                .where(
                    SchoolSsoConfiguration.school_id == school_id,
                    SchoolSsoConfiguration.provider == provider,
                )
                .values(
                    oauth_credential_ciphertext=ciphertext,
                    connection_status=SsoConnectionStatus.CONNECTED,
                    last_connection_error=None,
                    reauthorised_at=datetime.now(UTC),
                )
            )

    async def mark_callback_succeeded(
        self,
        *,
        school_id: UUID,
        provider: SsoProvider,
        succeeded_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(SchoolSsoConfiguration)
                .where(
                    SchoolSsoConfiguration.school_id == school_id,
                    SchoolSsoConfiguration.provider == provider,
                )
                .values(
                    enabled=True,
                    connection_status=SsoConnectionStatus.CONNECTED,
                    last_connection_error=None,
                    connection_checked_at=succeeded_at,
                    reauthorised_at=succeeded_at,
                    disconnected_at=None,
                    disconnected_by_user_id=None,
                    next_scheduled_sync_at=succeeded_at + timedelta(days=1),
                )
            )

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
        triggered_by_user_id: UUID | None = None,
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
                triggered_manually=triggered_by_user_id is not None,
                triggered_by_user_id=triggered_by_user_id,
                started_at=now,
                completed_at=now,
            )
            session.add(run)
            await session.flush()

            for student in batch.students:
                student_user = await _upsert_roster_user(
                    session, school_id, provider, student
                )
                await _sync_student_classes(
                    session,
                    school_id=school_id,
                    student=student_user,
                    class_external_ids=student.class_external_ids,
                )
                imported_students += 1
            issue_ids: list[UUID] = []
            for teacher in batch.teachers:
                teacher_user = await _upsert_roster_user(
                    session, school_id, provider, teacher
                )
                imported_teachers += 1
                for class_external_id in teacher.class_external_ids:
                    school_class = await _class_for_external_id(
                        session,
                        school_id,
                        class_external_id,
                    )
                    if school_class is None:
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
                            resolution_hint=MISSING_CLASS_RESOLUTION_HINT,
                        )
                        session.add(issue)
                        issue_ids.append(issue.id)
                        continue
                    await _sync_teacher_class(
                        session,
                        school_id=school_id,
                        teacher=teacher_user,
                        school_class=school_class,
                        source_reference=class_external_id,
                    )
            run.imported_students = imported_students
            run.imported_teachers = imported_teachers
            run.missing_teacher_class_mappings = missing_mappings
            run.status = (
                RosterSyncStatus.PARTIAL_MANUAL_REVIEW
                if missing_mappings
                else RosterSyncStatus.COMPLETED
            )
            # A sync that reached the provider proves the credentials work, so
            # a previous "needs attention" clears itself without the admin
            # having to dismiss anything. A deliberate disconnect stands.
            await session.execute(
                update(SchoolSsoConfiguration)
                .where(
                    SchoolSsoConfiguration.school_id == school_id,
                    SchoolSsoConfiguration.provider == provider,
                    SchoolSsoConfiguration.connection_status
                    == SsoConnectionStatus.NEEDS_ATTENTION,
                )
                .values(
                    connection_status=SsoConnectionStatus.CONNECTED,
                    last_connection_error=None,
                    connection_checked_at=now,
                    next_scheduled_sync_at=now + timedelta(days=1),
                )
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
        user.role = account.role
        user.sso_external_id = external_id
        user.status = UserStatus.ACTIVE
        user.first_name = account.first_name
        user.last_name = account.last_name
        user.email = account.email.casefold()
    await session.flush()
    return user


async def _class_for_external_id(
    session: AsyncSession,
    school_id: UUID,
    external_id: str,
) -> Class | None:
    return await session.scalar(
        select(Class).where(
            Class.school_id == school_id,
            func.lower(Class.class_code) == external_id.casefold(),
            Class.archived_at.is_(None),
        )
    )


async def _sync_student_classes(
    session: AsyncSession,
    *,
    school_id: UUID,
    student: User,
    class_external_ids: tuple[str, ...],
) -> None:
    for external_id in class_external_ids:
        school_class = await _class_for_external_id(session, school_id, external_id)
        if school_class is None:
            continue
        enrollment_id = await session.scalar(
            select(StudentClassEnrollment.id).where(
                StudentClassEnrollment.student_id == student.id,
                StudentClassEnrollment.class_id == school_class.id,
            )
        )
        if enrollment_id is None:
            session.add(
                StudentClassEnrollment(
                    student_id=student.id,
                    class_id=school_class.id,
                )
            )


async def _sync_teacher_class(
    session: AsyncSession,
    *,
    school_id: UUID,
    teacher: User,
    school_class: Class,
    source_reference: str,
) -> None:
    existing = await session.scalar(
        select(TeacherClassAssignment).where(
            TeacherClassAssignment.teacher_id == teacher.id,
            TeacherClassAssignment.class_id == school_class.id,
            TeacherClassAssignment.removed_at.is_(None),
        )
    )
    if existing is not None:
        if existing.source is TeacherAssignmentSource.ROSTER_SYNC:
            existing.source_reference = source_reference
        return
    primary_exists = await session.scalar(
        select(TeacherClassAssignment.id).where(
            TeacherClassAssignment.class_id == school_class.id,
            TeacherClassAssignment.role == TeacherAssignmentRole.PRIMARY,
            TeacherClassAssignment.removed_at.is_(None),
        )
    )
    session.add(
        TeacherClassAssignment(
            school_id=school_id,
            teacher_id=teacher.id,
            class_id=school_class.id,
            role=(
                TeacherAssignmentRole.CO_TEACHER
                if primary_exists is not None
                else TeacherAssignmentRole.PRIMARY
            ),
            source=TeacherAssignmentSource.ROSTER_SYNC,
            source_reference=source_reference,
        )
    )


def _school_config(record: SchoolSsoConfiguration) -> SsoSchoolConfig:
    return SsoSchoolConfig(
        school_id=record.school_id,
        school_url_slug=record.school_url_slug,
        provider=record.provider,
        client_id=record.client_id,
        tenant_id=record.tenant_id,
        hosted_domain=record.hosted_domain,
        provider_credential=record.oauth_credential_ciphertext,
    )


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
