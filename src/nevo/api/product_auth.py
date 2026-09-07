import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from nevo.api.auth import (
    AuthServiceDependency,
    OptionalPrincipalDependency,
    PrincipalDependency,
    SessionResponse,
)
from nevo.api.consent import ConsentServiceDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import actor_user, require_school_actor
from nevo.api.response_models import (
    AuthSessionRecordResponse,
    BulkInvitationResponse,
    InvitationResponse,
    JoinAcceptedResponse,
    JoinInspectionResponse,
    ParentRightResponse,
    SchoolCodeResponse,
)
from nevo.auth.config import AuthSettings
from nevo.auth.security import Argon2idCredentialHasher
from nevo.consent.entities import ConsentActor
from nevo.consent.errors import ConsentError
from nevo.consent.service import ConsentService
from nevo.db.models.account import (
    Class,
    School,
    StudentClassEnrollment,
    User,
)
from nevo.db.models.auth import AuthSession
from nevo.db.models.frontend_support import Notification, PasswordResetToken
from nevo.db.models.permission import Admin, AdminScopeAssignment
from nevo.db.models.product import (
    SchoolInvitation,
    StudentOnboardingGrant,
)
from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    ConsentStatus,
    ConsentType,
    NotificationType,
    UserRole,
    UserStatus,
)
from nevo.domain.consent.vocabulary import ParentContactMethod, ParentRightType
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.notifications.email import EmailDeliveryUnavailableError, ResendEmailDelivery

router = APIRouter(prefix="/api/v1", tags=["product access"])


@lru_cache
def credential_hasher() -> Argon2idCredentialHasher:
    settings = AuthSettings()  # type: ignore[call-arg]
    return Argon2idCredentialHasher(
        settings.auth_password_pepper.get_secret_value(),
        settings.auth_pin_pepper.get_secret_value(),
    )


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SchoolCodeRequest(BaseModel):
    school_code: str = Field(alias="schoolCode", min_length=2, max_length=50)


class PinUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pin: str = Field(pattern=r"^\d{6}$")
    onboarding_token: str | None = Field(default=None, alias="onboardingToken", min_length=32)
    first_name: str | None = Field(default=None, alias="firstName", min_length=1, max_length=100)
    last_name: str | None = Field(default=None, alias="lastName", max_length=100)
    age: int | None = Field(default=None, ge=5, le=21)


class PinUpdateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str
    user_id: UUID = Field(alias="userId")
    login_identifier: str | None = Field(alias="loginIdentifier")
    session: SessionResponse | None = None


class PinResetRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    school_code: str = Field(alias="schoolCode", min_length=2, max_length=50)
    login_identifier: str = Field(alias="loginIdentifier", min_length=1, max_length=50)


class PasswordResetCompleteRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    password: str = Field(min_length=8, max_length=1024)


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    current_password: str = Field(alias="currentPassword", min_length=8, max_length=1024)
    new_password: str = Field(alias="newPassword", min_length=8, max_length=1024)
    end_other_sessions: bool = Field(default=True, alias="endOtherSessions")


class SchoolRegistrationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    school_name: str = Field(alias="schoolName", min_length=2, max_length=255)
    admin_name: str = Field(alias="adminName", min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=1024)

    @field_validator("school_name", "admin_name")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        """min_length counts characters, so "  " reached the handler.

        There it named a school nothing at all, and raised IndexError on the
        administrator's name split - a 500 for what is a bad request.
        """
        stripped = value.strip()
        if len(stripped) < 2:
            raise ValueError("must contain at least two non-blank characters")
        return stripped


class InvitationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    role: UserRole = Field(pattern="^(teacher|student)$")
    first_name: str | None = Field(default=None, alias="firstName", max_length=100)
    last_name: str | None = Field(default=None, alias="lastName", max_length=100)
    email: EmailStr | None = None
    parent_contact: str | None = Field(default=None, alias="parentContact", max_length=255)
    class_id: UUID | None = Field(default=None, alias="classId")


class JoinRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    password: str | None = Field(default=None, min_length=8, max_length=1024)
    pin: str | None = Field(default=None, pattern=r"^\d{6}$")
    first_name: str | None = Field(default=None, alias="firstName", max_length=100)
    last_name: str | None = Field(default=None, alias="lastName", max_length=100)


class ParentRightRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_type: ParentRightType = Field(alias="requestType")
    reason: str | None = Field(default=None, max_length=2000)


@router.post("/auth/school-code/verify", response_model=SchoolCodeResponse)
async def verify_school_code(
    payload: SchoolCodeRequest,
    session: DatabaseSession,
) -> dict[str, object]:
    school = await session.scalar(
        select(School).where(func.lower(School.school_code) == payload.school_code.casefold())
    )
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School code not found")
    classes = (
        await session.scalars(
            select(Class)
            .where(Class.school_id == school.id, Class.archived_at.is_(None))
            .order_by(Class.name)
        )
    ).all()
    return {
        "schoolId": str(school.id),
        "schoolName": school.name,
        "authMethod": school.auth_method.value,
        "classes": [
            {"id": str(item.id), "name": item.name, "yearGroup": item.year_group}
            for item in classes
        ],
    }


@router.post(
    "/auth/pin",
    response_model=PinUpdateResponse,
    openapi_extra={"security": []},
)
async def set_pin(
    payload: PinUpdateRequest,
    principal: OptionalPrincipalDependency,
    session: DatabaseSession,
    auth_service: AuthServiceDependency,
    response: Response,
) -> dict[str, object]:
    if principal is not None:
        user = await actor_user(session, principal)
        if user.role is not UserRole.STUDENT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="PIN is for student accounts",
            )
        user.pin_hash = credential_hasher().hash_pin(payload.pin)
        user.auth_method = AuthMethod.PIN
        await session.commit()
        return {
            "status": "updated",
            "userId": user.id,
            "loginIdentifier": user.login_identifier,
            "session": None,
        }

    if not payload.onboarding_token or not payload.first_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="onboardingToken and firstName are required before sign-in",
        )
    grant = await session.scalar(
        select(StudentOnboardingGrant).where(
            StudentOnboardingGrant.token_digest == _digest(payload.onboarding_token),
            StudentOnboardingGrant.used_at.is_(None),
            StudentOnboardingGrant.expires_at > datetime.now(UTC),
        )
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="Onboarding session is invalid or expired")
    identifier = f"NV-{secrets.token_hex(3).upper()}"
    user = User(
        school_id=grant.school_id,
        role=UserRole.STUDENT,
        auth_method=AuthMethod.PIN,
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip() if payload.last_name else None,
        login_identifier=identifier,
        age_band=str(payload.age) if payload.age is not None else None,
        pin_hash=credential_hasher().hash_pin(payload.pin),
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    await session.flush()
    session.add(StudentClassEnrollment(student_id=user.id, class_id=grant.class_id))
    grant.used_at = datetime.now(UTC)
    await session.commit()
    issued = await auth_service.issue_for_provisioned_user(user.id)
    response.headers["Cache-Control"] = "no-store"
    return {
        "status": "created",
        "userId": user.id,
        "loginIdentifier": identifier,
        "session": SessionResponse.from_issued(issued),
    }


@router.post("/auth/pin/reset", status_code=status.HTTP_202_ACCEPTED)
async def request_pin_reset(
    payload: PinResetRequest,
    session: DatabaseSession,
) -> dict[str, str]:
    school = await session.scalar(
        select(School).where(func.lower(School.school_code) == payload.school_code.casefold())
    )
    student = None
    if school:
        student = await session.scalar(
            select(User).where(
                User.school_id == school.id,
                User.role == UserRole.STUDENT,
                func.lower(User.login_identifier) == payload.login_identifier.casefold(),
            )
        )
    if student and school:
        from nevo.db.models.frontend_support import Notification

        admins = (
            await session.scalars(
                select(User).where(
                    User.school_id == school.id,
                    User.role.in_({UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}),
                    User.status == UserStatus.ACTIVE,
                )
            )
        ).all()
        for admin in admins:
            session.add(
                Notification(
                    recipient_id=admin.id,
                    recipient_role=admin.role.value,
                    type="pin_reset_requested",
                    category="account",
                    title="Student needs a new PIN",
                    description=(f"{student.first_name or 'A student'} requested help signing in."),
                    navigates_to=f"/admin/students/{student.id}",
                )
            )
        await session.commit()
    return {"status": "accepted"}


@router.post("/auth/password-reset/complete")
async def complete_password_reset(
    payload: PasswordResetCompleteRequest,
    session: DatabaseSession,
) -> dict[str, str]:
    now = datetime.now(UTC)
    record = await session.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_digest == _digest(payload.token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link is invalid or expired",
        )
    user = await session.get(User, record.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link is invalid or expired",
        )
    user.password_hash = credential_hasher().hash_password(payload.password)
    user.auth_method = AuthMethod.EMAIL_PASSWORD
    record.used_at = now
    await session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now, revocation_reason="password_reset")
    )
    await session.commit()
    return {"status": "password_updated"}


@router.get("/auth/sessions", response_model=list[AuthSessionRecordResponse])
async def list_auth_sessions(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[dict[str, object]]:
    rows = (
        await session.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == principal.user_id)
            .order_by(AuthSession.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(item.id),
            "current": item.id == principal.session_id,
            "createdAt": item.created_at,
            "lastSeenAt": item.last_seen_at,
            "expiresAt": item.expires_at,
            "active": item.revoked_at is None,
        }
        for item in rows
    ]


@router.post("/auth/sessions/revoke-others", status_code=204)
async def revoke_other_auth_sessions(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    await session.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == principal.user_id,
            AuthSession.id != principal.session_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(
            revoked_at=datetime.now(UTC),
            revocation_reason="user_revoked",
        )
    )
    await session.commit()


@router.delete("/auth/sessions/{session_id}", status_code=204)
async def revoke_auth_session(
    session_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    record = await session.get(AuthSession, session_id)
    if record is None or record.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    if record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)
        record.revocation_reason = "user_revoked"
        await session.commit()


@router.post("/auth/password/change")
async def change_password(
    payload: PasswordChangeRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, str]:
    user = await actor_user(session, principal)
    hasher = credential_hasher()
    if not hasher.verify_password(user.password_hash, payload.current_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password did not match",
        )
    user.password_hash = hasher.hash_password(payload.new_password)
    if payload.end_other_sessions:
        await session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.id != principal.session_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC), revocation_reason="password_change")
        )
    await session.commit()
    return {"status": "password_updated"}


class SchoolRegistrationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    school_id: UUID = Field(alias="schoolId")
    admin_id: UUID = Field(alias="adminId")
    school_code: str = Field(alias="schoolCode")


@router.post(
    "/schools/register",
    response_model=SchoolRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_school(
    payload: SchoolRegistrationRequest,
    session: DatabaseSession,
) -> SchoolRegistrationResponse:
    existing_id = await session.scalar(
        select(User.id).where(func.lower(User.email) == str(payload.email).casefold())
    )
    if existing_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already belongs to an account",
        )
    school_name = payload.school_name
    admin_name = payload.admin_name
    school_id, user_id, admin_id = uuid4(), uuid4(), uuid4()
    slug_base = "-".join(school_name.casefold().split())[:80] or "school"
    school = School(
        id=school_id,
        name=school_name,
        school_code=secrets.token_hex(4).upper(),
        school_url_slug=f"{slug_base}-{secrets.token_hex(2)}",
        auth_method=AuthMethod.EMAIL_PASSWORD,
    )
    names = admin_name.split(maxsplit=1)
    user = User(
        id=user_id,
        school_id=school_id,
        role=UserRole.OTHER_ADMIN,
        auth_method=AuthMethod.EMAIL_PASSWORD,
        first_name=names[0],
        last_name=names[1] if len(names) > 1 else None,
        email=str(payload.email).casefold(),
        password_hash=credential_hasher().hash_password(payload.password),
        status=UserStatus.ACTIVE,
    )
    # These models intentionally use raw UUID foreign keys rather than ORM
    # relationships. Flush each dependency tier so SQLAlchemy cannot schedule
    # the admin row before the user it references.
    session.add(school)
    await session.flush()
    session.add(user)
    await session.flush()
    session.add(
        Notification(
            recipient_id=user_id,
            recipient_role=UserRole.OTHER_ADMIN.value,
            type=NotificationType.ADMIN_WELCOME.value,
            title="Your school workspace is ready",
            description="You can now add your team, classes, and learners.",
            navigates_to="/admin/overview",
            category="account",
        )
    )
    session.add(Admin(id=admin_id, user_id=user_id, school_id=school_id))
    await session.flush()
    # One statement for every scope. Seven separate inserts meant seven round
    # trips to the database, which is most of what registration used to spend
    # its time on.
    await session.execute(
        insert(AdminScopeAssignment),
        [
            {
                "admin_id": admin_id,
                "scope": scope,
                "granted_by_user_id": user_id,
            }
            for scope in PermissionScope
        ],
    )
    try:
        await session.commit()
    except IntegrityError as error:
        # Two registrations for the same address can both pass the check above
        # before either commits. The loser is a duplicate, not a server fault.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already belongs to an account",
        ) from error
    return SchoolRegistrationResponse(
        schoolId=school_id,
        adminId=user_id,
        schoolCode=school.school_code,
    )


async def _create_invitation(
    payload: InvitationRequest,
    actor: User,
    session: DatabaseSession,
    mailer: ResendEmailDelivery,
) -> dict[str, object]:
    if payload.class_id:
        school_class = await session.get(Class, payload.class_id)
        if school_class is None or school_class.school_id != actor.school_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found")
    token = secrets.token_urlsafe(32)
    record = SchoolInvitation(
        school_id=actor.school_id,
        role=payload.role,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=str(payload.email).casefold() if payload.email else None,
        parent_contact=payload.parent_contact,
        class_id=payload.class_id,
        token_digest=_digest(token),
        expires_at=datetime.now(UTC) + timedelta(days=14),
        created_by_id=actor.id,
    )
    session.add(record)
    await session.commit()
    delivery_status = "not_requested"
    if record.email:
        try:
            await _send_invitation(mailer, record, token)
            delivery_status = "sent"
        except EmailDeliveryUnavailableError:
            delivery_status = "email_not_configured"
    return {
        "id": str(record.id),
        "token": token,
        "status": record.status,
        "expiresAt": record.expires_at,
        "deliveryStatus": delivery_status,
        "consentStatus": record.consent_request_status,
    }


@router.post("/invites", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invite(
    payload: InvitationRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
    request: Request,
) -> dict[str, object]:
    actor = await require_school_actor(session, principal, roles={"senco_admin", "other_admin"})
    return await _create_invitation(payload, actor, session, _mailer(request))


@router.post(
    "/invites/bulk",
    response_model=BulkInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_bulk_invites(
    payloads: list[InvitationRequest],
    principal: PrincipalDependency,
    session: DatabaseSession,
    request: Request,
) -> dict[str, object]:
    actor = await require_school_actor(session, principal, roles={"senco_admin", "other_admin"})
    created, rejected = [], []
    for index, payload in enumerate(payloads[:500]):
        try:
            created.append(await _create_invitation(payload, actor, session, _mailer(request)))
        except HTTPException as error:
            rejected.append({"row": index + 1, "reason": str(error.detail)})
    return {"created": created, "rejected": rejected}


@router.get("/invites", response_model=list[InvitationResponse])
async def list_invites(
    principal: PrincipalDependency,
    session: DatabaseSession,
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[dict[str, object]]:
    actor = await require_school_actor(session, principal, roles={"senco_admin", "other_admin"})
    query = select(SchoolInvitation).where(SchoolInvitation.school_id == actor.school_id)
    if status_filter:
        query = query.where(SchoolInvitation.status == status_filter)
    rows = (await session.scalars(query.order_by(SchoolInvitation.created_at.desc()))).all()
    return [
        {
            "id": str(item.id),
            "role": item.role,
            "email": item.email,
            "name": " ".join(filter(None, (item.first_name, item.last_name))),
            "status": item.status,
            "expiresAt": item.expires_at,
            "consentStatus": item.consent_request_status,
        }
        for item in rows
    ]


@router.patch("/invites/{invitation_id}/resend", response_model=InvitationResponse)
async def resend_invite(
    invitation_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    request: Request,
) -> dict[str, object]:
    actor = await require_school_actor(session, principal, roles={"senco_admin", "other_admin"})
    record = await session.get(SchoolInvitation, invitation_id)
    if record is None or record.school_id != actor.school_id or record.status != "pending":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    token = secrets.token_urlsafe(32)
    record.token_digest = _digest(token)
    record.expires_at = datetime.now(UTC) + timedelta(days=14)
    await session.commit()
    delivery_status = "not_requested"
    if record.email:
        try:
            await _send_invitation(_mailer(request), record, token)
            delivery_status = "sent"
        except EmailDeliveryUnavailableError:
            delivery_status = "email_not_configured"
    return {
        "id": str(record.id),
        "token": token,
        "expiresAt": record.expires_at,
        "deliveryStatus": delivery_status,
        "consentStatus": record.consent_request_status,
    }


def _mailer(request: Request) -> ResendEmailDelivery:
    mailer = getattr(request.app.state, "email_delivery", None)
    if not isinstance(mailer, ResendEmailDelivery):
        raise HTTPException(status_code=503, detail="Email delivery is unavailable")
    return mailer


async def _send_invitation(
    mailer: ResendEmailDelivery,
    record: SchoolInvitation,
    token: str,
) -> None:
    if record.email is None:
        return
    link = f"{mailer.frontend_base_url}/join/{token}"
    await mailer.send(
        to=record.email,
        subject="Your Nevo invitation",
        text=(
            "You have been invited to join your school on Nevo.\n\n"
            f"Open this secure link to finish setting up your account:\n{link}\n\n"
            "The link expires in 14 days."
        ),
    )


@router.delete("/invites/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invitation_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    actor = await require_school_actor(session, principal, roles={"senco_admin", "other_admin"})
    record = await session.get(SchoolInvitation, invitation_id)
    if record is None or record.school_id != actor.school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    record.status = "revoked"
    record.revoked_at = datetime.now(UTC)
    await session.commit()


async def _join_record(token: str, session: DatabaseSession) -> SchoolInvitation:
    record = await session.scalar(
        select(SchoolInvitation).where(SchoolInvitation.token_digest == _digest(token))
    )
    if record is None or record.status != "pending" or record.expires_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Join link is invalid or expired",
        )
    return record


@router.get("/join/{token}", response_model=JoinInspectionResponse)
async def inspect_join(token: str, session: DatabaseSession) -> dict[str, object]:
    record = await _join_record(token, session)
    school = await session.get(School, record.school_id)
    return {
        "status": "valid",
        "role": record.role,
        "schoolName": school.name if school else None,
        "expiresAt": record.expires_at,
    }


@router.post(
    "/join/{token}/accept",
    response_model=JoinAcceptedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_join(
    token: str,
    payload: JoinRequest,
    session: DatabaseSession,
    request: Request,
) -> dict[str, object]:
    record = await _join_record(token, session)
    if record.role == "teacher" and not (payload.password and record.email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Teacher password and email are required",
        )
    student_credentials_valid = payload.pin or (record.email and payload.password)
    if record.role == "student" and not student_credentials_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Student PIN or email and password are required",
        )
    identifier = f"NV-{secrets.token_hex(3).upper()}"
    user = User(
        school_id=record.school_id,
        role=UserRole(record.role),
        auth_method=(
            AuthMethod.EMAIL_PASSWORD if record.email and payload.password else AuthMethod.PIN
        ),
        first_name=payload.first_name or record.first_name,
        last_name=payload.last_name or record.last_name,
        email=record.email,
        login_identifier=identifier if record.role == "student" else None,
        password_hash=(
            credential_hasher().hash_password(payload.password) if payload.password else None
        ),
        pin_hash=credential_hasher().hash_pin(payload.pin) if payload.pin else None,
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    await session.flush()
    if record.class_id and record.role == "student":
        session.add(StudentClassEnrollment(student_id=user.id, class_id=record.class_id))
    record.status, record.accepted_at = "joined", datetime.now(UTC)
    await session.commit()
    consent_status: ConsentStatus | None = None
    if record.role == "student":
        consent_status = ConsentStatus.NOT_SENT
        if record.parent_contact:
            service = getattr(request.app.state, "consent_service", None)
            if isinstance(service, ConsentService):
                method = (
                    ParentContactMethod.EMAIL
                    if "@" in record.parent_contact
                    else ParentContactMethod.SMS
                )
                try:
                    await service.request_parent_consent(
                        ConsentActor(
                            user_id=record.created_by_id,
                            school_id=record.school_id,
                        ),
                        student_id=user.id,
                        parent_name="Parent or guardian",
                        parent_contact=record.parent_contact,
                        contact_method=method,
                        consent_types=frozenset({ConsentType.DATA_PROCESSING}),
                    )
                    consent_status = ConsentStatus.PENDING
                    record.consent_request_status = ConsentStatus.PENDING.value
                    await session.commit()
                except ConsentError:
                    record.consent_request_status = ConsentStatus.NOT_SENT.value
                    await session.commit()
    return {
        "userId": str(user.id),
        "role": user.role.value,
        "loginIdentifier": user.login_identifier,
        "consentStatus": consent_status,
    }


@router.post(
    "/parent/{token}/rights",
    response_model=ParentRightResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def exercise_parent_right(
    token: str,
    payload: ParentRightRequest,
    service: ConsentServiceDependency,
) -> ParentRightResponse:
    """Record a right the parent exercises against their own child's data.

    The token is hashed by the consent token service, not by this module's
    plain digest. Using the wrong one here meant every valid link resolved to
    "Parent link not found", so no parent could object or withdraw at all.
    """
    outcome = await service.exercise_parent_right(
        token=token,
        request_type=payload.request_type,
        reason=payload.reason,
    )
    if outcome is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This consent link is invalid, expired, or already used",
        )
    return ParentRightResponse(
        request_id=outcome.request_id,
        request_type=outcome.request_type,
        status=outcome.status,
        reason_recorded=outcome.reason_recorded,
    )
