from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import School, User
from nevo.db.models.permission import (
    Admin,
    AdminInvitation,
    AdminScopeAssignment,
)
from nevo.domain.accounts.vocabulary import AuthMethod, UserRole, UserStatus
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.permissions.entities import (
    AcceptedInvitation,
    AdminTeamMember,
    InvitationDraft,
    PermissionSnapshot,
)
from nevo.permissions.errors import (
    LastOversightAdminError,
    TeamMemberAlreadyExistsError,
)


class SqlAlchemyPermissionRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def snapshot(self, user_id: UUID) -> PermissionSnapshot | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(User, School.auth_method, Admin.id)
                    .outerjoin(School, School.id == User.school_id)
                    .outerjoin(Admin, Admin.user_id == User.id)
                    .where(User.id == user_id)
                )
            ).one_or_none()
            if row is None:
                return None
            user, school_auth_method, admin_id = row
            scopes = await self._active_scopes(session, admin_id)
        return PermissionSnapshot(
            user_id=user.id,
            school_id=user.school_id,
            role=user.role.value,
            status=user.status.value,
            school_auth_method=school_auth_method.value
            if school_auth_method is not None
            else None,
            assigned_scopes=scopes,
        )

    async def list_team(self, school_id: UUID) -> list[AdminTeamMember]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(Admin, User)
                    .join(User, User.id == Admin.user_id)
                    .where(Admin.school_id == school_id)
                    .order_by(User.last_name, User.first_name, User.email)
                )
            ).all()
            admin_ids = [admin.id for admin, _ in rows]
            scopes_by_admin = await self._scopes_for_admins(session, admin_ids)

        return [
            self._team_member(
                admin,
                user,
                scopes_by_admin.get(admin.id, frozenset()),
            )
            for admin, user in rows
        ]

    async def create_invitation(self, draft: InvitationDraft) -> InvitationDraft:
        try:
            async with self._sessions.begin() as session:
                existing = await session.scalar(
                    select(User)
                    .where(func.lower(User.email) == draft.email)
                    .with_for_update()
                    .limit(1)
                )
                if existing is not None:
                    if (
                        existing.status is not UserStatus.INVITED
                        or existing.school_id != draft.school_id
                    ):
                        raise TeamMemberAlreadyExistsError
                    admin = await session.scalar(
                        select(Admin)
                        .where(Admin.user_id == existing.id)
                        .with_for_update()
                    )
                    if admin is None:
                        raise TeamMemberAlreadyExistsError
                    await session.execute(
                        update(AdminInvitation)
                        .where(
                            AdminInvitation.user_id == existing.id,
                            AdminInvitation.accepted_at.is_(None),
                            AdminInvitation.revoked_at.is_(None),
                        )
                        .values(revoked_at=draft.created_at)
                    )
                    await self._replace_assignment_rows(
                        session,
                        admin_id=admin.id,
                        scopes=draft.scopes,
                        changed_by_user_id=draft.invited_by_user_id,
                        changed_at=draft.created_at,
                    )
                    existing.role = UserRole(draft.role)
                    stored = replace(
                        draft,
                        user_id=existing.id,
                        admin_id=admin.id,
                    )
                else:
                    stored = draft
                    session.add(
                        User(
                            id=stored.user_id,
                            school_id=stored.school_id,
                            role=UserRole(stored.role),
                            auth_method=AuthMethod.EMAIL_PASSWORD,
                            email=stored.email,
                            status=UserStatus.INVITED,
                        )
                    )
                    session.add(
                        Admin(
                            id=stored.admin_id,
                            user_id=stored.user_id,
                            school_id=stored.school_id,
                            created_by_user_id=stored.invited_by_user_id,
                            created_at=stored.created_at,
                            updated_at=stored.created_at,
                        )
                    )
                    for scope in stored.scopes:
                        session.add(
                            AdminScopeAssignment(
                                admin_id=stored.admin_id,
                                scope=scope,
                                granted_by_user_id=stored.invited_by_user_id,
                                granted_at=stored.created_at,
                            )
                        )
                session.add(
                    AdminInvitation(
                        id=stored.invitation_id,
                        user_id=stored.user_id,
                        school_id=stored.school_id,
                        role=UserRole(stored.role),
                        token_digest=stored.token_digest,
                        invited_by_user_id=stored.invited_by_user_id,
                        created_at=stored.created_at,
                        expires_at=stored.expires_at,
                    )
                )
                await session.flush()
                return stored
        except IntegrityError as error:
            raise TeamMemberAlreadyExistsError from error

    async def accept_invitation(
        self,
        *,
        token_digest: str,
        password_hash: str,
        accepted_at: datetime,
    ) -> AcceptedInvitation | None:
        async with self._sessions.begin() as session:
            invitation = await session.scalar(
                select(AdminInvitation)
                .where(AdminInvitation.token_digest == token_digest)
                .with_for_update()
            )
            if (
                invitation is None
                or invitation.accepted_at is not None
                or invitation.revoked_at is not None
                or invitation.expires_at <= accepted_at
            ):
                return None

            user = await session.scalar(
                select(User)
                .where(User.id == invitation.user_id)
                .with_for_update()
            )
            if user is None or user.status is not UserStatus.INVITED:
                return None

            user.password_hash = password_hash
            user.auth_method = AuthMethod.EMAIL_PASSWORD
            user.status = UserStatus.ACTIVE
            user.deactivated_at = None
            invitation.accepted_at = accepted_at
            return AcceptedInvitation(
                user_id=user.id,
                school_id=invitation.school_id,
                role=user.role.value,
            )

    async def replace_scopes(
        self,
        *,
        school_id: UUID,
        target_user_id: UUID,
        scopes: frozenset[PermissionScope],
        changed_by_user_id: UUID,
        changed_at: datetime,
    ) -> AdminTeamMember | None:
        async with self._sessions.begin() as session:
            await session.execute(
                select(School.id)
                .where(School.id == school_id)
                .with_for_update()
            )
            row = (
                await session.execute(
                    select(Admin, User)
                    .join(User, User.id == Admin.user_id)
                    .where(
                        Admin.school_id == school_id,
                        User.id == target_user_id,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                return None
            admin, user = row
            current = await self._active_scopes_for_update(session, admin.id)
            removed = current - scopes

            if PermissionScope.OVERSIGHT in removed:
                oversight_count = await session.scalar(
                    select(func.count())
                    .select_from(AdminScopeAssignment)
                    .join(Admin, Admin.id == AdminScopeAssignment.admin_id)
                    .join(User, User.id == Admin.user_id)
                    .where(
                        Admin.school_id == school_id,
                        User.status == UserStatus.ACTIVE,
                        AdminScopeAssignment.scope == PermissionScope.OVERSIGHT,
                        AdminScopeAssignment.revoked_at.is_(None),
                    )
                )
                if oversight_count is None or oversight_count <= 1:
                    raise LastOversightAdminError

            await self._replace_assignment_rows(
                session,
                admin_id=admin.id,
                scopes=scopes,
                changed_by_user_id=changed_by_user_id,
                changed_at=changed_at,
                current=current,
            )
            await session.flush()
            return self._team_member(admin, user, scopes)

    @staticmethod
    async def _active_scopes_for_update(
        session: AsyncSession,
        admin_id: UUID,
    ) -> frozenset[PermissionScope]:
        assignments = await session.scalars(
            select(AdminScopeAssignment)
            .where(
                AdminScopeAssignment.admin_id == admin_id,
                AdminScopeAssignment.revoked_at.is_(None),
            )
            .with_for_update()
        )
        return frozenset(assignment.scope for assignment in assignments)

    @classmethod
    async def _replace_assignment_rows(
        cls,
        session: AsyncSession,
        *,
        admin_id: UUID,
        scopes: frozenset[PermissionScope],
        changed_by_user_id: UUID,
        changed_at: datetime,
        current: frozenset[PermissionScope] | None = None,
    ) -> None:
        active = (
            current
            if current is not None
            else await cls._active_scopes_for_update(session, admin_id)
        )
        removed = active - scopes
        added = scopes - active
        if removed:
            await session.execute(
                update(AdminScopeAssignment)
                .where(
                    AdminScopeAssignment.admin_id == admin_id,
                    AdminScopeAssignment.scope.in_(removed),
                    AdminScopeAssignment.revoked_at.is_(None),
                )
                .values(revoked_at=changed_at)
            )
        for scope in added:
            session.add(
                AdminScopeAssignment(
                    admin_id=admin_id,
                    scope=scope,
                    granted_by_user_id=changed_by_user_id,
                    granted_at=changed_at,
                )
            )

    @staticmethod
    async def _active_scopes(
        session: AsyncSession,
        admin_id: UUID | None,
    ) -> frozenset[PermissionScope]:
        if admin_id is None:
            return frozenset()
        scopes = await session.scalars(
            select(AdminScopeAssignment.scope).where(
                AdminScopeAssignment.admin_id == admin_id,
                AdminScopeAssignment.revoked_at.is_(None),
            )
        )
        return frozenset(scopes)

    @staticmethod
    async def _scopes_for_admins(
        session: AsyncSession,
        admin_ids: list[UUID],
    ) -> dict[UUID, frozenset[PermissionScope]]:
        if not admin_ids:
            return {}
        rows = (
            await session.execute(
                select(
                    AdminScopeAssignment.admin_id,
                    AdminScopeAssignment.scope,
                ).where(
                    AdminScopeAssignment.admin_id.in_(admin_ids),
                    AdminScopeAssignment.revoked_at.is_(None),
                )
            )
        ).all()
        grouped: dict[UUID, set[PermissionScope]] = {}
        for admin_id, scope in rows:
            grouped.setdefault(admin_id, set()).add(scope)
        return {
            admin_id: frozenset(scopes)
            for admin_id, scopes in grouped.items()
        }

    @staticmethod
    def _team_member(
        admin: Admin,
        user: User,
        scopes: frozenset[PermissionScope],
    ) -> AdminTeamMember:
        return AdminTeamMember(
            user_id=user.id,
            admin_id=admin.id,
            school_id=admin.school_id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            role=user.role.value,
            status=user.status.value,
            scopes=scopes,
        )
