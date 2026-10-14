"""Create a verified SENCo QA account in an existing test school."""

import argparse
import asyncio
import json
import secrets
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from sqlalchemy import func, select

from nevo.auth.config import AuthSettings
from nevo.auth.wiring import build_credential_hasher
from nevo.core.config import get_settings
from nevo.db.models.account import School, User
from nevo.db.models.permission import Admin, AdminScopeAssignment, LearningSupportGrant
from nevo.db.session import create_engine, create_session_factory
from nevo.domain.accounts.vocabulary import AuthMethod, UserRole, UserStatus
from nevo.domain.permissions.vocabulary import AdminAccessLevel, PermissionScope


async def seed(school_code: str, email: str, verify_url: str | None) -> None:
    engine = create_engine(get_settings().database_url)
    password = secrets.token_urlsafe(24)
    hasher = build_credential_hasher(AuthSettings())
    try:
        async with create_session_factory(engine).begin() as session:
            school = await session.scalar(select(School).where(School.school_code == school_code))
            if school is None:
                raise ValueError("Test school not found")
            if "e2e" not in school.name.casefold() and "test" not in school.name.casefold():
                raise ValueError("This script only seeds explicitly named test schools")
            granter = await session.scalar(
                select(User)
                .where(
                    User.school_id == school.id,
                    User.role.in_([UserRole.OTHER_ADMIN, UserRole.SENCO_ADMIN]),
                    User.status == UserStatus.ACTIVE,
                )
                .order_by(User.created_at)
                .limit(1)
            )
            if granter is None:
                raise ValueError("An active school administrator must already exist")
            user = await session.scalar(
                select(User).where(func.lower(User.email) == email.casefold())
            )
            if user is not None and (
                user.school_id != school.id or user.role != UserRole.SENCO_ADMIN
            ):
                raise ValueError("That email already belongs to another account")
            if user is None:
                seats = await session.scalar(
                    select(func.count(Admin.id))
                    .join(User, User.id == Admin.user_id)
                    .where(
                        Admin.school_id == school.id,
                        User.status.in_([UserStatus.ACTIVE, UserStatus.INVITED]),
                    )
                )
                if seats >= school.admin_seat_limit:
                    raise ValueError("The test school has used all admin seats")
                user = User(
                    id=uuid4(),
                    school_id=school.id,
                    email=email.casefold(),
                    role=UserRole.SENCO_ADMIN,
                    auth_method=AuthMethod.EMAIL_PASSWORD,
                    first_name="E2E",
                    last_name="Learning Support",
                )
                session.add(user)
            user.password_hash = hasher.hash_password(password)
            user.status = UserStatus.ACTIVE
            user.email_confirmed_at = datetime.now(UTC)
            await session.flush()
            admin = await session.scalar(select(Admin).where(Admin.user_id == user.id))
            if admin is None:
                admin = Admin(
                    id=uuid4(),
                    user_id=user.id,
                    school_id=school.id,
                    access_level=AdminAccessLevel.STANDARD,
                    created_by_user_id=granter.id,
                )
                session.add(admin)
                await session.flush()
            if (
                await session.scalar(
                    select(AdminScopeAssignment.id).where(
                        AdminScopeAssignment.admin_id == admin.id,
                        AdminScopeAssignment.scope == PermissionScope.SENCO,
                        AdminScopeAssignment.revoked_at.is_(None),
                    )
                )
                is None
            ):
                session.add(
                    AdminScopeAssignment(
                        admin_id=admin.id,
                        scope=PermissionScope.SENCO,
                        granted_by_user_id=granter.id,
                    )
                )
            if (
                await session.scalar(
                    select(LearningSupportGrant.id).where(
                        LearningSupportGrant.holder_user_id == user.id,
                        LearningSupportGrant.revoked_at.is_(None),
                    )
                )
                is None
            ):
                session.add(
                    LearningSupportGrant(
                        school_id=school.id, holder_user_id=user.id, granted_by_user_id=granter.id
                    )
                )
        live_status = None
        if verify_url:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{verify_url.rstrip('/')}/api/v1/auth/login",
                    json={"method": "password", "email": email, "password": password},
                )
                live_status = response.status_code
                if live_status == 200:
                    data = response.json()
                    token = data.get("accessToken") or data.get("access_token")
                    me = await client.get(
                        f"{verify_url.rstrip('/')}/api/v1/users/me",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    print("Live users/me:", me.status_code)
        print(
            json.dumps(
                {
                    "email": email,
                    "password": password,
                    "role": "senco_admin",
                    "schoolCode": school_code,
                    "liveLoginStatus": live_status,
                }
            )
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-code", required=True)
    parser.add_argument("--email", default="senco.e2e@nevolearning.com")
    parser.add_argument("--verify-url")
    args = parser.parse_args()
    asyncio.run(seed(args.school_code, args.email, args.verify_url))
