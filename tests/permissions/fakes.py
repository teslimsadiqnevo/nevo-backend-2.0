from dataclasses import replace
from datetime import datetime
from uuid import UUID

from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.permissions.entities import (
    AcceptedInvitation,
    AdminTeamMember,
    InvitationDraft,
    PermissionSnapshot,
)
from nevo.permissions.errors import LastOversightAdminError


class MemoryPermissionRepository:
    def __init__(self, snapshots: list[PermissionSnapshot] | None = None) -> None:
        self.snapshots = {
            snapshot.user_id: snapshot for snapshot in snapshots or []
        }
        self.team: dict[UUID, list[AdminTeamMember]] = {}
        self.invitations: dict[str, InvitationDraft] = {}
        self.password_hashes: dict[UUID, str] = {}
        self.raise_last_oversight = False

    async def snapshot(self, user_id: UUID) -> PermissionSnapshot | None:
        return self.snapshots.get(user_id)

    async def list_team(self, school_id: UUID) -> list[AdminTeamMember]:
        return list(self.team.get(school_id, []))

    async def create_invitation(self, draft: InvitationDraft) -> InvitationDraft:
        existing_member = next(
            (
                member
                for member in self.team.get(draft.school_id, [])
                if member.email == draft.email and member.status == "invited"
            ),
            None,
        )
        if existing_member is not None:
            for digest, invitation in list(self.invitations.items()):
                if invitation.user_id == existing_member.user_id:
                    del self.invitations[digest]
            draft = replace(
                draft,
                user_id=existing_member.user_id,
                admin_id=existing_member.admin_id,
            )
            self.team[draft.school_id] = [
                replace(member, role=draft.role, scopes=draft.scopes)
                if member.user_id == draft.user_id
                else member
                for member in self.team[draft.school_id]
            ]
        else:
            member = AdminTeamMember(
                user_id=draft.user_id,
                admin_id=draft.admin_id,
                school_id=draft.school_id,
                email=draft.email,
                first_name=None,
                last_name=None,
                role=draft.role,
                status="invited",
                scopes=draft.scopes,
            )
            self.team.setdefault(draft.school_id, []).append(member)
        self.invitations[draft.token_digest] = draft
        return draft

    async def accept_invitation(
        self,
        *,
        token_digest: str,
        password_hash: str,
        accepted_at: datetime,
    ) -> AcceptedInvitation | None:
        invitation = self.invitations.pop(token_digest, None)
        if invitation is None or invitation.expires_at <= accepted_at:
            return None
        self.password_hashes[invitation.user_id] = password_hash
        members = self.team.get(invitation.school_id, [])
        self.team[invitation.school_id] = [
            replace(member, status="active")
            if member.user_id == invitation.user_id
            else member
            for member in members
        ]
        return AcceptedInvitation(
            user_id=invitation.user_id,
            school_id=invitation.school_id,
            role=invitation.role,
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
        del changed_by_user_id, changed_at
        if self.raise_last_oversight:
            raise LastOversightAdminError
        members = self.team.get(school_id, [])
        for index, member in enumerate(members):
            if member.user_id == target_user_id:
                updated = replace(member, scopes=scopes)
                members[index] = updated
                return updated
        return None


class DeterministicInvitationTokens:
    def __init__(self) -> None:
        self.counter = 0

    def issue(self) -> tuple[str, str]:
        self.counter += 1
        token = f"invitation-token-{self.counter}-" + ("x" * 32)
        return token, self.digest(token)

    @staticmethod
    def digest(token: str) -> str:
        return f"digest:{token}"


class FakePasswordHasher:
    @staticmethod
    def hash_password(password: str) -> str:
        return f"hashed:{password}"
