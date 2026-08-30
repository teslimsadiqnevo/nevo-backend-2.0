import hashlib
import secrets
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import (
    actor_user,
    require_class_access,
    require_school_actor,
    require_student_access,
)
from nevo.api.response_models import (
    ClassSummaryResponse,
    IdCodeResponse,
    IdNameResponse,
    NotificationPreferenceResponse,
    OpsFeedbackResponse,
    OpsOverviewResponse,
    PersonalSettingsResponse,
    PinIssueResponse,
    SchoolOverviewResponse,
    SchoolResponse,
    StudentDetailResponse,
    StudentEnrollmentResponse,
    StudentMoveResponse,
    StudentSummaryResponse,
    TeacherDetailResponse,
    TeacherSummaryResponse,
)
from nevo.auth.security import Argon2idCredentialHasher
from nevo.db.models.account import Class, School, StudentClassEnrollment, User
from nevo.db.models.auth import AuthSession
from nevo.db.models.frontend_support import Notification
from nevo.db.models.product import (
    EnrollmentHistory,
    FeedbackSubmission,
    NotificationPreference,
)
from nevo.db.models.signal_event import LessonSession
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.accounts.vocabulary import AuthMethod, UserRole, UserStatus

router = APIRouter(prefix="/api/v1", tags=["school administration"])
SearchQuery = Annotated[str | None, Query(max_length=100)]
ClassFilter = Annotated[UUID | None, Query(alias="classId")]
InactiveFilter = Annotated[bool, Query(alias="includeInactive")]


class SchoolPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=2, max_length=255)
    profile: dict[str, object] | None = None
    academic_config: dict[str, object] | None = Field(default=None, alias="academicConfig")
    retention_policy: str | None = Field(
        default=None,
        alias="retentionPolicy",
        pattern="^(contract|contract_plus_3_years|contract_plus_7_years)$",
    )


class ClassWrite(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=255)
    year_group: str | None = Field(default=None, alias="yearGroup", max_length=20)


class StudentEnroll(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    first_name: str = Field(alias="firstName", min_length=1, max_length=100)
    last_name: str = Field(alias="lastName", min_length=1, max_length=100)
    class_id: UUID = Field(alias="classId")
    email: str | None = None
    age_band: str | None = Field(default=None, alias="ageBand", max_length=40)


class StudentMove(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    class_id: UUID = Field(alias="classId")


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    feedback_type: str = Field(alias="type", min_length=1, max_length=40)
    note: str = Field(min_length=1, max_length=5000)
    context: str = Field(default="unknown", max_length=120)


class PreferenceWrite(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: str = Field(min_length=1, max_length=80)
    in_app: bool = Field(alias="inApp")
    email: bool


class PersonalSettingsWrite(BaseModel):
    preferences: dict[str, object] = Field(default_factory=dict)


def _name(user: User) -> str:
    return " ".join(part for part in (user.first_name, user.last_name) if part) or "Nevo user"


def _school_payload(school: School) -> dict[str, object]:
    return {
        "id": str(school.id),
        "name": school.name,
        "code": school.school_code,
        "slug": school.school_url_slug,
        "profile": school.profile,
        "academicConfig": school.academic_config,
        "retentionPolicy": school.retention_policy,
        "retentionDays": school.data_retention_days,
    }


@router.get("/school", response_model=SchoolResponse)
async def school_detail(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    user = await require_school_actor(session, principal)
    school = await session.get(School, user.school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="School not found")
    return _school_payload(school)


@router.patch("/school", response_model=SchoolResponse)
async def update_school(
    payload: SchoolPatch,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    user = await require_school_actor(
        session,
        principal,
        roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN},
    )
    school = await session.get(School, user.school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="School not found")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes:
        school.name = changes["name"]
    if "profile" in changes:
        school.profile = changes["profile"]
    if "academic_config" in changes:
        school.academic_config = changes["academic_config"]
    if "retention_policy" in changes:
        school.retention_policy = changes["retention_policy"]
    await session.commit()
    return _school_payload(school)


@router.get("/school/overview", response_model=SchoolOverviewResponse)
async def school_overview(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    user = await require_school_actor(session, principal)
    school_id = user.school_id
    counts = {}
    for role in (
        UserRole.STUDENT,
        UserRole.TEACHER,
        UserRole.SENCO_ADMIN,
        UserRole.OTHER_ADMIN,
    ):
        counts[role.value] = await session.scalar(
            select(func.count(User.id)).where(
                User.school_id == school_id,
                User.role == role,
                User.status != UserStatus.DEACTIVATED,
            )
        )
    counts["classes"] = await session.scalar(
        select(func.count(Class.id)).where(
            Class.school_id == school_id,
            Class.archived_at.is_(None),
        )
    )
    return {"schoolId": str(school_id), "counts": counts}


@router.get("/classes", response_model=list[ClassSummaryResponse])
async def list_classes(
    principal: PrincipalDependency,
    session: DatabaseSession,
    include_archived: bool = Query(False, alias="includeArchived"),
) -> list[dict[str, object]]:
    user = await require_school_actor(session, principal)
    query = select(Class).where(Class.school_id == user.school_id)
    if not include_archived:
        query = query.where(Class.archived_at.is_(None))
    classes = (await session.scalars(query.order_by(Class.name))).all()
    result: list[dict[str, object]] = []
    for item in classes:
        student_count = await session.scalar(
            select(func.count(StudentClassEnrollment.id)).where(
                StudentClassEnrollment.class_id == item.id
            )
        )
        result.append(
            {
                "id": str(item.id),
                "name": item.name,
                "code": item.class_code,
                "yearGroup": item.year_group,
                "source": item.source,
                "studentCount": student_count or 0,
                "archivedAt": item.archived_at,
            }
        )
    return result


@router.post("/classes", response_model=IdCodeResponse, status_code=status.HTTP_201_CREATED)
async def create_class(
    payload: ClassWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    user = await require_school_actor(
        session, principal, roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    school_class = Class(
        school_id=user.school_id,
        name=payload.name,
        year_group=payload.year_group,
        class_code=secrets.token_hex(3).upper(),
        source="manual",
    )
    session.add(school_class)
    await session.commit()
    return {"id": str(school_class.id), "code": school_class.class_code}


@router.patch("/classes/{class_id}", response_model=IdNameResponse)
async def update_class(
    class_id: UUID,
    payload: ClassWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    user = await require_school_actor(
        session, principal, roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    school_class = await require_class_access(session, user, class_id)
    school_class.name = payload.name
    school_class.year_group = payload.year_group
    await session.commit()
    return {"id": str(school_class.id), "name": school_class.name}


@router.get("/classes/{class_id}", response_model=ClassSummaryResponse)
async def class_detail(
    class_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(session, principal)
    school_class = await require_class_access(session, actor, class_id)
    students = await session.scalar(
        select(func.count(StudentClassEnrollment.id)).where(
            StudentClassEnrollment.class_id == class_id
        )
    )
    return {
        "id": str(school_class.id),
        "name": school_class.name,
        "code": school_class.class_code,
        "yearGroup": school_class.year_group,
        "studentCount": students or 0,
        "archivedAt": school_class.archived_at,
    }


@router.post("/classes/{class_id}/archive", status_code=204)
async def archive_class(
    class_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    user = await require_school_actor(
        session, principal, roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    school_class = await require_class_access(session, user, class_id)
    school_class.archived_at = datetime.now(UTC)
    await session.commit()


@router.post("/classes/{class_id}/restore", status_code=204)
async def restore_class(
    class_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    user = await require_school_actor(
        session, principal, roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    school_class = await require_class_access(session, user, class_id)
    school_class.archived_at = None
    await session.commit()


@router.get("/teachers", response_model=list[TeacherSummaryResponse])
async def list_teachers(
    principal: PrincipalDependency,
    session: DatabaseSession,
    search: SearchQuery = None,
) -> list[dict[str, object]]:
    actor = await require_school_actor(session, principal)
    query = select(User).where(
        User.school_id == actor.school_id,
        User.role == UserRole.TEACHER,
    )
    if search:
        value = f"%{search.casefold()}%"
        query = query.where(
            func.lower(func.concat(User.first_name, " ", User.last_name)).like(value)
        )
    teachers = (await session.scalars(query.order_by(User.first_name))).all()
    return [
        {
            "id": str(item.id),
            "name": _name(item),
            "email": item.email,
            "status": item.status.value,
        }
        for item in teachers
    ]


@router.get("/teachers/{teacher_id}", response_model=TeacherDetailResponse)
async def teacher_detail(
    teacher_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(session, principal)
    teacher = await session.get(User, teacher_id)
    if teacher is None or teacher.school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="Teacher not found")
    assignments = (
        await session.scalars(
            select(TeacherClassAssignment).where(
                TeacherClassAssignment.teacher_id == teacher.id,
                TeacherClassAssignment.removed_at.is_(None),
            )
        )
    ).all()
    return {
        "id": str(teacher.id),
        "name": _name(teacher),
        "email": teacher.email,
        "status": teacher.status.value,
        "classIds": [str(item.class_id) for item in assignments],
    }


@router.post("/teachers/{teacher_id}/revoke", status_code=204)
async def revoke_teacher(
    teacher_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    actor = await require_school_actor(
        session, principal, roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    teacher = await session.get(User, teacher_id)
    if teacher is None or teacher.school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="Teacher not found")
    teacher.status = UserStatus.DEACTIVATED
    teacher.deactivated_at = datetime.now(UTC)
    await session.commit()


@router.get("/students", response_model=list[StudentSummaryResponse])
async def list_students(
    principal: PrincipalDependency,
    session: DatabaseSession,
    class_id: ClassFilter = None,
    include_inactive: InactiveFilter = False,
) -> list[dict[str, object]]:
    actor = await require_school_actor(session, principal)
    query = select(User).where(
        User.school_id == actor.school_id,
        User.role == UserRole.STUDENT,
    )
    if not include_inactive:
        query = query.where(User.status != UserStatus.DEACTIVATED)
    if class_id:
        await require_class_access(session, actor, class_id)
        query = query.join(StudentClassEnrollment).where(
            StudentClassEnrollment.class_id == class_id
        )
    students = (await session.scalars(query.order_by(User.first_name))).all()
    return [
        {
            "id": str(item.id),
            "name": _name(item),
            "loginIdentifier": item.login_identifier,
            "status": item.status.value,
            "ageBand": item.age_band,
        }
        for item in students
    ]


@router.post(
    "/students",
    response_model=StudentEnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def enroll_student(
    payload: StudentEnroll,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(
        session, principal, roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    await require_class_access(session, actor, payload.class_id)
    identifier = f"NV-{secrets.token_hex(3).upper()}"
    student = User(
        school_id=actor.school_id,
        role=UserRole.STUDENT,
        auth_method=AuthMethod.PIN,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        login_identifier=identifier,
        age_band=payload.age_band,
        status=UserStatus.ACTIVE,
    )
    session.add(student)
    await session.flush()
    session.add(StudentClassEnrollment(student_id=student.id, class_id=payload.class_id))
    session.add(
        EnrollmentHistory(
            student_id=student.id,
            school_id=actor.school_id,
            to_class_id=payload.class_id,
            action="enrolled",
            actor_user_id=actor.id,
        )
    )
    await session.commit()
    return {"id": str(student.id), "loginIdentifier": identifier}


@router.get("/students/{student_id}", response_model=StudentDetailResponse)
async def student_detail(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    await require_student_access(session, principal, student_id)
    student = await session.get(User, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    class_ids = (
        await session.scalars(
            select(StudentClassEnrollment.class_id).where(
                StudentClassEnrollment.student_id == student_id
            )
        )
    ).all()
    return {
        "id": str(student.id),
        "firstName": student.first_name,
        "lastName": student.last_name,
        "loginIdentifier": student.login_identifier,
        "email": student.email,
        "status": student.status.value,
        "ageBand": student.age_band,
        "classIds": [str(item) for item in class_ids],
        "firstUse": student.is_first_use,
    }


@router.patch("/students/{student_id}/class", response_model=StudentMoveResponse)
async def move_student(
    student_id: UUID,
    payload: StudentMove,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    actor = await require_school_actor(
        session, principal, roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    student = await session.get(User, student_id)
    if student is None or student.school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="Student not found")
    await require_class_access(session, actor, payload.class_id)
    old_class_id = await session.scalar(
        select(StudentClassEnrollment.class_id)
        .where(StudentClassEnrollment.student_id == student_id)
        .limit(1)
    )
    await session.execute(
        delete(StudentClassEnrollment).where(StudentClassEnrollment.student_id == student_id)
    )
    session.add(StudentClassEnrollment(student_id=student_id, class_id=payload.class_id))
    session.add(
        EnrollmentHistory(
            student_id=student_id,
            school_id=actor.school_id,
            from_class_id=old_class_id,
            to_class_id=payload.class_id,
            action="moved",
            actor_user_id=actor.id,
        )
    )
    await session.commit()
    return {"studentId": str(student_id), "classId": str(payload.class_id)}


async def _set_student_status(
    student_id: UUID,
    actor: User,
    db: DatabaseSession,
    active: bool,
) -> None:
    student = await db.get(User, student_id)
    if student is None or student.school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="Student not found")
    student.status = UserStatus.ACTIVE if active else UserStatus.DEACTIVATED
    student.deactivated_at = None if active else datetime.now(UTC)
    await db.commit()


@router.post("/students/{student_id}/deactivate", status_code=204)
async def deactivate_student(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    actor = await require_school_actor(
        session, principal, roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    await _set_student_status(student_id, actor, session, active=False)


@router.post("/students/{student_id}/restore", status_code=204)
async def restore_student(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    actor = await require_school_actor(
        session, principal, roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    await _set_student_status(student_id, actor, session, active=True)


@router.delete("/students/{student_id}", status_code=204)
async def anonymize_student(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    actor = await require_school_actor(
        session, principal, roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    student = await session.get(User, student_id)
    if student is None or student.school_id != actor.school_id:
        raise HTTPException(status_code=404, detail="Student not found")
    suffix = secrets.token_hex(8)
    student.first_name = "Former"
    student.last_name = "Student"
    student.email = None
    student.login_identifier = f"deleted-{suffix}"
    student.password_hash = None
    student.pin_hash = None
    student.baseline_profile = {}
    student.engine_config = {}
    student.preferences = {}
    student.status = UserStatus.DEACTIVATED
    student.deactivated_at = datetime.now(UTC)
    await session.commit()


@router.post("/students/{student_id}/pin/reset", response_model=PinIssueResponse)
async def issue_student_pin(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    request: Request,
) -> dict[str, object]:
    actor = await require_school_actor(session, principal, roles={"senco_admin", "other_admin"})
    student = await session.get(User, student_id)
    if (
        student is None
        or student.school_id != actor.school_id
        or student.role is not UserRole.STUDENT
    ):
        raise HTTPException(status_code=404, detail="Student not found")
    hasher = getattr(request.app.state, "credential_hasher", None)
    if not isinstance(hasher, Argon2idCredentialHasher):
        raise HTTPException(status_code=503, detail="Credential service unavailable")
    pin = f"{secrets.randbelow(1_000_000):06d}"
    student.pin_hash = hasher.hash_pin(pin)
    student.auth_method = AuthMethod.PIN
    now = datetime.now(UTC)
    await session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == student.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now, revocation_reason="pin_reset")
    )
    await session.commit()
    return {
        "studentId": str(student.id),
        "pin": pin,
        "issuedAt": now,
        "mustShareSecurely": True,
    }


@router.get("/notifications/unread-exists")
async def unread_exists(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, bool]:
    exists = await session.scalar(
        select(Notification.id)
        .where(
            Notification.recipient_id == principal.user_id,
            Notification.read.is_(False),
            Notification.archived_at.is_(None),
        )
        .limit(1)
    )
    return {"unread": exists is not None}


@router.post("/notifications/read-all", status_code=204)
async def read_all_notifications(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    records = (
        await session.scalars(
            select(Notification).where(
                Notification.recipient_id == principal.user_id,
                Notification.read.is_(False),
            )
        )
    ).all()
    for record in records:
        record.read = True
    await session.commit()


@router.post("/notifications/{notification_id}/archive", status_code=204)
async def archive_notification(
    notification_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    record = await session.get(Notification, notification_id)
    if record is None or record.recipient_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Notification not found")
    record.archived_at = datetime.now(UTC)
    await session.commit()


@router.post("/notifications/{notification_id}/restore", status_code=204)
async def restore_notification(
    notification_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> None:
    result = await session.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.recipient_id == principal.user_id,
        )
        .values(archived_at=None)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    await session.commit()


@router.get("/notification-preferences", response_model=list[NotificationPreferenceResponse])
async def notification_preferences(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[dict[str, object]]:
    records = (
        await session.scalars(
            select(NotificationPreference).where(
                NotificationPreference.user_id == principal.user_id
            )
        )
    ).all()
    return [
        {"category": item.category, "inApp": item.in_app, "email": item.email} for item in records
    ]


@router.put("/notification-preferences", response_model=list[NotificationPreferenceResponse])
async def update_notification_preferences(
    payload: list[PreferenceWrite],
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[dict[str, object]]:
    for item in payload:
        record = await session.scalar(
            select(NotificationPreference).where(
                NotificationPreference.user_id == principal.user_id,
                NotificationPreference.category == item.category,
            )
        )
        if record is None:
            record = NotificationPreference(
                user_id=principal.user_id,
                category=item.category,
            )
            session.add(record)
        record.in_app = item.in_app
        record.email = item.email
    await session.commit()
    return await notification_preferences(principal, session)


@router.get("/settings/me", response_model=PersonalSettingsResponse)
async def personal_settings(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    user = await actor_user(session, principal)
    return {"userId": str(user.id), "preferences": user.preferences}


@router.put("/settings/me", response_model=PersonalSettingsResponse)
async def update_personal_settings(
    payload: PersonalSettingsWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    user = await actor_user(session, principal)
    user.preferences = payload.preferences
    await session.commit()
    return {"userId": str(user.id), "preferences": user.preferences}


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    payload: FeedbackRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, str]:
    user = await actor_user(session, principal)
    account_ref = hashlib.sha256(str(user.id).encode()).hexdigest()[:16]
    record = FeedbackSubmission(
        account_ref=account_ref,
        school_id=user.school_id,
        role=user.role.value,
        feedback_type=payload.feedback_type,
        note=payload.note,
        context=payload.context,
    )
    session.add(record)
    await session.commit()
    return {"id": str(record.id), "status": record.status}


@router.get("/ops/feedback", response_model=list[OpsFeedbackResponse])
async def ops_feedback(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[dict[str, object]]:
    user = await actor_user(session, principal)
    if user.role is not UserRole.OTHER_ADMIN:
        raise HTTPException(status_code=403, detail="Ops access required")
    rows = (
        await session.scalars(
            select(FeedbackSubmission)
            .where(FeedbackSubmission.school_id == user.school_id)
            .order_by(FeedbackSubmission.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(item.id),
            "accountRef": item.account_ref,
            "role": item.role,
            "type": item.feedback_type,
            "note": item.note,
            "context": item.context,
            "status": item.status,
            "createdAt": item.created_at,
        }
        for item in rows
    ]


@router.get("/ops/overview", response_model=OpsOverviewResponse)
async def ops_overview(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    user = await actor_user(session, principal)
    if user.role is not UserRole.OTHER_ADMIN:
        raise HTTPException(status_code=403, detail="Ops access required")
    return {
        "schools": 1,
        "activeUsers": await session.scalar(
            select(func.count(User.id)).where(
                User.school_id == user.school_id,
                User.status == UserStatus.ACTIVE,
            )
        )
        or 0,
        "lessonSessions": await session.scalar(
            select(func.count(LessonSession.id))
            .join(User, User.id == LessonSession.student_id)
            .where(User.school_id == user.school_id)
        )
        or 0,
        "rawTouchSignalsExposed": 0,
    }
