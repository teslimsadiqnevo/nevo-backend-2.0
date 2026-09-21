"""Who may open the deepest view of a named child, and who decided that.

The learning support surface shows a child's accommodations, their adaptation
history, their help-seeking and their understanding. Nobody holds it by
default: if the registering administrator got it automatically, every school
would begin with its proprietor holding that view of every child in it.

A hard wall by identity would break the legitimate case - the schools being
sold to have actual learning support staff - so this is a recorded decision
instead. The school can see who holds it and when they were given it, and so
can Nevo. That turns a proprietor holding the role from an accommodation into
a signal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import User
from nevo.db.models.permission import Admin, AdminScopeAssignment, LearningSupportGrant
from nevo.domain.permissions.vocabulary import PermissionScope

router = APIRouter(prefix="/api/v1/learning-support", tags=["permissions"])

ADMIN_ROLES = {"senco_admin", "other_admin"}


class LearningSupportHolder(CamelResponse):
    """One person who can open the learning support surface."""

    user_id: UUID
    name: str
    role: str
    granted_at: datetime
    granted_by: UUID


class LearningSupportHolders(CamelResponse):
    """What the compliance screen shows, and what a grant screen asks about.

    Empty is a real answer and the surface says so plainly: at setup nobody
    holds this, and a school has to choose somebody.
    """

    holders: list[LearningSupportHolder]
    #: True when the person asking holds it themselves.
    viewer_holds_it: bool


class GrantRequest(BaseModel):
    model_config = CAMEL_CONFIG

    user_id: UUID
    #: True when the school is handing the role over rather than adding a
    #: second holder. Nevo does not decide this silently in either direction,
    #: so the console asks and sends the answer.
    replace_existing: bool = False


async def _holders(session: AsyncSession, school_id: UUID | None) -> list[LearningSupportGrant]:
    rows = await session.scalars(
        select(LearningSupportGrant)
        .where(
            LearningSupportGrant.school_id == school_id,
            LearningSupportGrant.revoked_at.is_(None),
        )
        .order_by(LearningSupportGrant.granted_at)
    )
    return list(rows)


async def holds_learning_support(session: AsyncSession, user: User) -> bool:
    """Whether this person may open the learning support surface.

    Asked by the endpoints that serve it, so the gate is the API's. Hiding the
    navigation is not a gate: the data is one request away from anyone who
    knows the path.
    """

    grant = await session.scalar(
        select(LearningSupportGrant.id).where(
            LearningSupportGrant.school_id == user.school_id,
            LearningSupportGrant.holder_user_id == user.id,
            LearningSupportGrant.revoked_at.is_(None),
        )
    )
    return grant is not None


async def require_learning_support(session: AsyncSession, user: User) -> None:
    if await holds_learning_support(session, user):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "learning_support_role_required",
            "message": (
                "This is the learning support view of a named child. An "
                "administrator can grant that role from the compliance screen, "
                "and the grant is recorded."
            ),
        },
    )


async def require_learning_support_if_admin(session: AsyncSession, user: User) -> None:
    """Hold an administrator to the role; leave everyone else as they were.

    A teacher sees what a teacher sees today, and a class teacher opening
    their own pupil is not what this ticket is about. What changes is an
    administrator - who can reach every child in the school - needing the
    role to open the learning support view of any of them.
    """

    if user.role.value not in ADMIN_ROLES:
        return
    await require_learning_support(session, user)


async def _view(
    session: AsyncSession, grants: list[LearningSupportGrant]
) -> list[LearningSupportHolder]:
    holders = []
    for grant in grants:
        person = await session.get(User, grant.holder_user_id)
        if person is None:
            continue
        holders.append(
            LearningSupportHolder(
                user_id=grant.holder_user_id,
                name=" ".join(part for part in (person.first_name, person.last_name) if part),
                role=person.role.value,
                granted_at=grant.granted_at,
                granted_by=grant.granted_by_user_id,
            )
        )
    return holders


@router.get("/holders", response_model=LearningSupportHolders)
async def list_holders(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LearningSupportHolders:
    """Who holds the role, for the compliance screen and for the grant screen."""

    actor = await require_school_actor(session, principal)
    grants = await _holders(session, actor.school_id)
    return LearningSupportHolders(
        holders=await _view(session, grants),
        viewer_holds_it=any(grant.holder_user_id == actor.id for grant in grants),
    )


@router.post(
    "/holders",
    response_model=LearningSupportHolders,
    status_code=status.HTTP_201_CREATED,
)
async def grant_learning_support(
    payload: GrantRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LearningSupportHolders:
    """Give somebody the role, deliberately and on the record.

    An administrator may grant it to themselves. That is allowed and it is
    exactly why it is written down: a proprietor holding the deepest view of
    every child is unusual rather than forbidden, and the school and Nevo can
    both see that it happened.
    """

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    holder = await session.get(User, payload.user_id)
    if holder is None or holder.school_id != actor.school_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That person is not in this school",
        )
    now = datetime.now(UTC)
    existing = await _holders(session, actor.school_id)
    if payload.replace_existing:
        for grant in existing:
            if grant.holder_user_id == payload.user_id:
                continue
            grant.revoked_at = now
            grant.revoked_by_user_id = actor.id
            # Handed over, not taken away. Different facts, and a school
            # reading its own history should be able to tell them apart.
            grant.handed_over = True
            await _drop_scope(session, grant.holder_user_id)
    if not any(grant.holder_user_id == payload.user_id for grant in existing):
        session.add(
            LearningSupportGrant(
                school_id=actor.school_id,
                holder_user_id=payload.user_id,
                granted_by_user_id=actor.id,
                granted_at=now,
            )
        )
        await _add_scope(session, payload.user_id, granted_by=actor.id)
    await session.flush()
    grants = await _holders(session, actor.school_id)
    holders = LearningSupportHolders(
        holders=await _view(session, grants),
        viewer_holds_it=any(grant.holder_user_id == actor.id for grant in grants),
    )
    await session.commit()
    return holders


@router.delete("/holders/{user_id}", response_model=LearningSupportHolders)
async def revoke_learning_support(
    user_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LearningSupportHolders:
    """Take the role away, recorded the same way it was given."""

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    now = datetime.now(UTC)
    for grant in await _holders(session, actor.school_id):
        if grant.holder_user_id != user_id:
            continue
        grant.revoked_at = now
        grant.revoked_by_user_id = actor.id
        await _drop_scope(session, user_id)
    await session.flush()
    grants = await _holders(session, actor.school_id)
    holders = LearningSupportHolders(
        holders=await _view(session, grants),
        viewer_holds_it=any(grant.holder_user_id == actor.id for grant in grants),
    )
    await session.commit()
    return holders


async def _admin(session: AsyncSession, user_id: UUID) -> Admin | None:
    admin: Admin | None = await session.scalar(select(Admin).where(Admin.user_id == user_id))
    return admin


async def _add_scope(session: AsyncSession, user_id: UUID, *, granted_by: UUID) -> None:
    """Keep the permission snapshot in step with the grant.

    The surface's own endpoints ask the grant directly, but everything that
    reads scopes - navigation, the permissions snapshot - should agree with
    it rather than tell a holder they have no such role.
    """

    admin = await _admin(session, user_id)
    if admin is None:
        return
    held = await session.scalar(
        select(AdminScopeAssignment.id).where(
            AdminScopeAssignment.admin_id == admin.id,
            AdminScopeAssignment.scope == PermissionScope.SENCO,
        )
    )
    if held is None:
        session.add(
            AdminScopeAssignment(
                admin_id=admin.id,
                scope=PermissionScope.SENCO,
                granted_by_user_id=granted_by,
            )
        )


async def _drop_scope(session: AsyncSession, user_id: UUID) -> None:
    admin = await _admin(session, user_id)
    if admin is None:
        return
    assignment = await session.scalar(
        select(AdminScopeAssignment).where(
            AdminScopeAssignment.admin_id == admin.id,
            AdminScopeAssignment.scope == PermissionScope.SENCO,
        )
    )
    if assignment is not None:
        await session.delete(assignment)
