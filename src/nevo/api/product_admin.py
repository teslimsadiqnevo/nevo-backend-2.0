import hashlib
import secrets
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.api.auth import PrincipalDependency
from nevo.api.consent_summary import empty_consent_summary, student_consent_summaries
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import (
    actor_user,
    require_class_access,
    require_school_actor,
    require_student_access,
)
from nevo.api.response_models import (
    AcademicConfig,
    CamelResponse,
    ClassSummaryResponse,
    IdCodeResponse,
    IdNameResponse,
    NotificationPreferenceResponse,
    NotificationPreferencesWriteResponse,
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
from nevo.db.models.consent import ParentLink
from nevo.db.models.frontend_support import Notification
from nevo.db.models.product import (
    DpaAcceptance,
    EnrollmentHistory,
    FeedbackSubmission,
    NotificationPreference,
)
from nevo.db.models.signal_event import LessonSession
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.accounts.age_bands import (
    AgeBand,
    band_for_date_of_birth,
    coerce_band,
)
from nevo.domain.accounts.classes import (
    academic_session,
    normalise_class_name,
    parse_class_name,
)
from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    NotificationCategory,
    UserRole,
    UserStatus,
)
from nevo.domain.consent.vocabulary import ParentContactMethod
from nevo.retention.anonymisation import anonymise_student
from nevo.subjects.resolution import (
    set_class_subjects,
    subjects_for_class,
    subjects_for_classes,
)

router = APIRouter(prefix="/api/v1", tags=["school administration"])
SearchQuery = Annotated[str | None, Query(max_length=100)]
ClassFilter = Annotated[UUID | None, Query(alias="classId")]
InactiveFilter = Annotated[bool, Query(alias="includeInactive")]


class SchoolPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=2, max_length=255)
    profile: dict[str, object] | None = None
    #: Validated rather than waved through: billing reads termStartDates, and
    #: an unreadable date there used to be swallowed with a log line, which
    #: meant a school was invoiced on dates it had not chosen.
    academic_config: AcademicConfig | None = Field(default=None, alias="academicConfig")
    retention_policy: str | None = Field(
        default=None,
        alias="retentionPolicy",
        pattern="^(contract|contract_plus_3_years|contract_plus_7_years)$",
    )


class ClassWrite(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=255)
    #: Read from the name ("JSS 2A" is JSS 2, section A) when not sent, so the
    #: console's one-field create still files a class under its year group.
    year_group: str | None = Field(default=None, alias="yearGroup", max_length=20)
    section: str | None = Field(default=None, max_length=20)
    #: Defaults to the school year the request falls in. A school creating
    #: next year's classes early sends the session it means.
    academic_session: str | None = Field(
        default=None,
        alias="academicSession",
        max_length=20,
    )
    capacity: int | None = Field(default=None, gt=0, le=500)
    #: What this class is taught, stated rather than derived. Sending a list
    #: replaces whatever was derived from assigned lessons; sending an empty
    #: list goes back to deriving them.
    subjects: list[Annotated[str, Field(min_length=1, max_length=80)]] | None = Field(
        default=None,
        max_length=20,
    )


class BulkClassWrite(BaseModel):
    """The year-group grid: a screen's worth of classes in one call."""

    model_config = ConfigDict(populate_by_name=True)

    classes: list[ClassWrite] = Field(min_length=1, max_length=200)


class ClassRejection(CamelResponse):
    """Why one class in a bulk create was not made.

    Per row, with the value that caused it, because a school creating thirty
    classes will not notice a count of failures - and did not, when an import
    of four hundred children reported only that some rows failed.
    """

    index: int
    field: str
    value: str
    reason: str


class BulkClassResponse(CamelResponse):
    created: list[IdCodeResponse]
    rejected: list[ClassRejection]


class StudentEnroll(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    first_name: str = Field(alias="firstName", min_length=1, max_length=100)
    last_name: str = Field(alias="lastName", min_length=1, max_length=100)
    class_id: UUID = Field(alias="classId")
    #: The school's own Student ID or Admission Number, and how this child
    #: signs in. Any string: Nigerian schools format these completely
    #: differently, so only uniqueness within the school is checked.
    #:
    #: Required, because a child without one cannot identify themselves at the
    #: door. SCRUM-202.
    admission_number: Annotated[str, Field(alias="admissionNumber", min_length=1, max_length=60)]
    #: Optional and rarely needed: the band is derived from the date of birth
    #: below, which is the better source. Accepted only as a fallback for a
    #: school that has an age but not a birthday to hand. SCRUM-175, ask B5.
    age_band: AgeBand | None = Field(default=None, alias="ageBand")
    #: The school's own record of when the child was born.
    #:
    #: Optional, because a school office mid-term may not have it to hand and
    #: refusing the enrolment over it would keep a child out of lessons. But
    #: it is the school's half of the two-point age check - the parent
    #: confirms the other half - so a child enrolled without one cannot have
    #: that check done until it is filled in.
    date_of_birth: date | None = Field(default=None, alias="dateOfBirth")
    #: Where this child's consent request is sent.
    #:
    #: Email only on this path, deliberately. A proprietor enrolling one child
    #: mid-term should not have to go and find a parent's full name first, and
    #: the parent supplies their own name at consent - which is better evidence
    #: than a name a school transcribed. The roster CSV asks for both because
    #: a school filling that file already has them to hand.
    #:
    #: This was briefly removed on the advice that a contact we do not yet act
    #: on should not be stored. That was wrong: consent gates activation, so
    #: the address has a purpose the moment it is entered.
    parent_email: EmailStr | None = Field(default=None, alias="parentEmail")

    @field_validator("date_of_birth")
    @classmethod
    def _not_in_the_future(cls, value: date | None) -> date | None:
        if value is not None and value > datetime.now(UTC).date():
            raise ValueError("A date of birth cannot be in the future.")
        return value


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

    # Deliberately a string, not the enum: an unknown category has to reach
    # the handler so it can be rejected on its own line. Typed on the way out.
    category: str = Field(min_length=1, max_length=80)
    in_app: bool = Field(alias="inApp")
    email: bool


#: One row per category, so the natural bound is the vocabulary itself plus
#: room for a client that repeats one. Unbounded, this was a query per row.
PreferenceWriteList = Annotated[list[PreferenceWrite], Field(max_length=50)]


class PersonalSettingsWrite(BaseModel):
    #: Merged into what is already stored, not swapped for it. Two clients
    #: hold different partial views of the same bag, so a replacing write
    #: means whichever saved last erases the other's keys. Send a key as null
    #: to remove it.
    preferences: dict[str, object] = Field(default_factory=dict)


class SchoolNarrativeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    headline: str
    summary: str
    highlights: list[str]
    generated_at: datetime = Field(alias="generatedAt")
    source: Literal["live_school_data"] = "live_school_data"


class DpaAcceptanceRequest(BaseModel):
    version: str = Field(min_length=1, max_length=40)


class DpaAcceptanceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    school_id: UUID = Field(alias="schoolId")
    version: str
    accepted_by_user_id: UUID = Field(alias="acceptedByUserId")
    accepted_by_name: str = Field(alias="acceptedByName")
    accepted_at: datetime = Field(alias="acceptedAt")


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
    if "academic_config" in changes and payload.academic_config is not None:
        # Dumped in JSON mode so the dates land as ISO strings, which is what
        # billing parses them back out of.
        school.academic_config = payload.academic_config.model_dump(
            mode="json",
            by_alias=False,
        )
    if "retention_policy" in changes:
        school.retention_policy = changes["retention_policy"]
    await session.commit()
    return _school_payload(school)


@router.get("/school/overview", response_model=SchoolOverviewResponse)
async def school_overview(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    """Roster headcounts for this school.

    Students are reported active and invited separately. A plan-cost screen
    multiplies a headcount by a rate, and whether a student who was invited
    but has never signed in should be billed is a commercial decision - not
    one this endpoint should make silently by returning a single total.
    """
    user = await require_school_actor(session, principal)
    school_id = user.school_id

    async def students_with(status: UserStatus) -> int:
        return int(
            await session.scalar(
                select(func.count(User.id)).where(
                    User.school_id == school_id,
                    User.role == UserRole.STUDENT,
                    User.status == status,
                )
            )
            or 0
        )

    async def staff(role: UserRole) -> int:
        return int(
            await session.scalar(
                select(func.count(User.id)).where(
                    User.school_id == school_id,
                    User.role == role,
                    User.status != UserStatus.DEACTIVATED,
                )
            )
            or 0
        )

    classes = int(
        await session.scalar(
            select(func.count(Class.id)).where(
                Class.school_id == school_id,
                Class.archived_at.is_(None),
            )
        )
        or 0
    )
    return {
        "schoolId": str(school_id),
        "counts": {
            "activeStudents": await students_with(UserStatus.ACTIVE),
            "invitedStudents": await students_with(UserStatus.INVITED),
            "teachers": await staff(UserRole.TEACHER),
            "sencoAdmins": await staff(UserRole.SENCO_ADMIN),
            "otherAdmins": await staff(UserRole.OTHER_ADMIN),
            "classes": classes,
        },
    }


@router.get("/school/narrative", response_model=SchoolNarrativeResponse)
async def school_narrative(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> SchoolNarrativeResponse:
    actor = await require_school_actor(
        session,
        principal,
        roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN},
    )
    student_count = int(
        await session.scalar(
            select(func.count(User.id)).where(
                User.school_id == actor.school_id,
                User.role == UserRole.STUDENT,
                User.status == UserStatus.ACTIVE,
            )
        )
        or 0
    )
    class_count = int(
        await session.scalar(
            select(func.count(Class.id)).where(
                Class.school_id == actor.school_id,
                Class.archived_at.is_(None),
            )
        )
        or 0
    )
    sessions_count = int(
        await session.scalar(
            select(func.count(LessonSession.id))
            .join(User, User.id == LessonSession.student_id)
            .where(User.school_id == actor.school_id)
        )
        or 0
    )
    highlights = [
        f"{student_count} active learner{'s' if student_count != 1 else ''}",
        f"{class_count} active class{'es' if class_count != 1 else ''}",
        f"{sessions_count} lesson session{'s' if sessions_count != 1 else ''} recorded",
    ]
    return SchoolNarrativeResponse(
        headline="Your school at a glance",
        summary=(
            f"Your school currently supports {student_count} active learners across "
            f"{class_count} active classes. Nevo has recorded {sessions_count} lesson "
            "sessions so far."
        ),
        highlights=highlights,
        generatedAt=datetime.now(UTC),
    )


async def _dpa_response(
    session: DatabaseSession,
    acceptance: DpaAcceptance,
) -> DpaAcceptanceResponse:
    accepted_by = await session.get(User, acceptance.accepted_by_user_id)
    return DpaAcceptanceResponse(
        id=acceptance.id,
        schoolId=acceptance.school_id,
        version=acceptance.version,
        acceptedByUserId=acceptance.accepted_by_user_id,
        acceptedByName=_name(accepted_by) if accepted_by else "Former administrator",
        acceptedAt=acceptance.accepted_at,
    )


@router.get("/school/dpa-acceptance", response_model=DpaAcceptanceResponse | None)
async def current_dpa_acceptance(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> DpaAcceptanceResponse | None:
    actor = await require_school_actor(
        session,
        principal,
        roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN},
    )
    acceptance = await session.scalar(
        select(DpaAcceptance)
        .where(DpaAcceptance.school_id == actor.school_id)
        .order_by(DpaAcceptance.accepted_at.desc())
        .limit(1)
    )
    return await _dpa_response(session, acceptance) if acceptance else None


@router.post(
    "/school/dpa-acceptance",
    response_model=DpaAcceptanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_dpa(
    payload: DpaAcceptanceRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> DpaAcceptanceResponse:
    actor = await require_school_actor(
        session,
        principal,
        roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN},
    )
    acceptance = await session.scalar(
        select(DpaAcceptance).where(
            DpaAcceptance.school_id == actor.school_id,
            DpaAcceptance.version == payload.version.strip(),
        )
    )
    if acceptance is None:
        acceptance = DpaAcceptance(
            school_id=actor.school_id,
            version=payload.version.strip(),
            accepted_by_user_id=actor.id,
            accepted_at=datetime.now(UTC),
        )
        session.add(acceptance)
        await session.commit()
    return await _dpa_response(session, acceptance)


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
    # Two aggregates for the whole page rather than two queries per class.
    # A school with forty classes was issuing eighty-one queries to render
    # the list every admin opens.
    class_ids = [item.id for item in classes]
    counts = await _student_counts(session, class_ids)
    teachers = await _teachers_by_class(session, class_ids)
    # The class's own scheme of work, which is authoritative for it. It used
    # to be derived from the subjects of lessons already assigned, so a class
    # with nothing assigned read as having no subjects at all. SCRUM-194.
    subjects_by_class = await subjects_for_classes(session, class_ids)
    result: list[dict[str, object]] = []
    for item in classes:
        student_count = counts.get(item.id, 0)
        subjects = subjects_by_class.get(item.id, [])
        result.append(
            {
                "id": str(item.id),
                "name": item.name,
                "code": item.class_code,
                "yearGroup": item.year_group,
                "section": item.section,
                "academicSession": item.academic_session,
                "capacity": item.capacity,
                "source": item.source,
                "subjects": subjects,
                "studentCount": student_count or 0,
                "teachers": teachers.get(item.id, []),
                "teacherCount": len(teachers.get(item.id, [])),
                "archivedAt": item.archived_at,
            }
        )
    return result


def _school_of(user: User) -> UUID:
    """The actor's school, narrowed.

    require_school_actor has already established there is one; the column is
    nullable because a Nevo-side account has no school, and that account cannot
    reach these routes. Raising rather than asserting so a wrong turn is a 403
    and not a 500.
    """

    if user.school_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "school_context_required",
                "message": "This action belongs to a school account.",
            },
        )
    return user.school_id


def _class_row(payload: ClassWrite, *, school_id: UUID | None, source: str = "manual") -> Class:
    """One class, with the parts of its name it did not have to be told.

    "JSS 2A" carries its year group and its section, and a school typing one
    field should not have to repeat them into three.
    """

    parsed = parse_class_name(payload.name)
    return Class(
        school_id=school_id,
        name=parsed.name,
        year_group=payload.year_group or parsed.year_group,
        section=payload.section or parsed.section,
        academic_session=payload.academic_session or academic_session(datetime.now(UTC).date()),
        capacity=payload.capacity,
        class_code=secrets.token_hex(3).upper(),
        source=source,
    )


async def _existing_class_name(
    session: AsyncSession,
    *,
    school_id: UUID | None,
    row: Class,
) -> Class | None:
    """The live class this one would collide with, if there is one."""

    existing: Class | None = await session.scalar(
        select(Class).where(
            Class.school_id == school_id,
            Class.academic_session == row.academic_session,
            Class.normalised_name == normalise_class_name(row.name),
            Class.archived_at.is_(None),
        )
    )
    return existing


def _duplicate_class_detail(row: Class, existing: Class) -> dict[str, object]:
    return {
        "code": "class_already_exists",
        "message": (
            f"{existing.name} already exists for {existing.academic_session}."
            " Rename this one, or open the existing class."
        ),
        "classId": str(existing.id),
        "name": row.name,
        "academicSession": row.academic_session,
    }


@router.post("/classes", response_model=IdCodeResponse, status_code=status.HTTP_201_CREATED)
async def create_class(
    payload: ClassWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    user = await require_school_actor(
        session, principal, roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    school_class = _class_row(payload, school_id=user.school_id)
    existing = await _existing_class_name(session, school_id=user.school_id, row=school_class)
    if existing is not None:
        # Named rather than reported as a status, because a school told only
        # that something conflicted has nowhere to go.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_duplicate_class_detail(school_class, existing),
        )
    session.add(school_class)
    await session.flush()
    if payload.subjects:
        await set_class_subjects(
            session,
            school_id=_school_of(user),
            class_id=school_class.id,
            typed=payload.subjects,
            created_by_user_id=user.id,
        )
    await session.commit()
    return {"id": str(school_class.id), "code": school_class.class_code}


@router.post(
    "/classes/bulk",
    response_model=BulkClassResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_classes(
    payload: BulkClassWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> BulkClassResponse:
    """The year-group grid: a screen's worth of classes at once.

    A class already there is rejected by name rather than failing the call, so
    an administrator who adds JSS 3C to a grid of classes that already exist
    gets JSS 3C, not an error and nothing.
    """

    user = await require_school_actor(
        session, principal, roles={UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}
    )
    created: list[IdCodeResponse] = []
    rejected: list[ClassRejection] = []
    seen: dict[tuple[str, str], int] = {}
    for index, item in enumerate(payload.classes):
        row = _class_row(item, school_id=user.school_id)
        key = (row.academic_session, normalise_class_name(row.name))
        if key in seen:
            rejected.append(
                ClassRejection(
                    index=index,
                    field="name",
                    value=item.name,
                    reason=(
                        f"The same class is on this list twice, at row {seen[key] + 1}"
                        f" and row {index + 1}."
                    ),
                )
            )
            continue
        existing = await _existing_class_name(session, school_id=user.school_id, row=row)
        if existing is not None:
            rejected.append(
                ClassRejection(
                    index=index,
                    field="name",
                    value=item.name,
                    reason=(f"{existing.name} already exists for {existing.academic_session}."),
                )
            )
            continue
        seen[key] = index
        session.add(row)
        await session.flush()
        if item.subjects:
            # Carried on the bulk path too: a school setting up nine classes at
            # once is not forced through nine separate edits. SCRUM-194.
            await set_class_subjects(
                session,
                school_id=_school_of(user),
                class_id=row.id,
                typed=item.subjects,
                created_by_user_id=user.id,
            )
        created.append(IdCodeResponse(id=row.id, code=row.class_code))
    await session.commit()
    return BulkClassResponse(created=created, rejected=rejected)


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
    if payload.subjects is not None:
        # Sent, so it is the class's scheme of work. An empty list clears it,
        # which is a school saying it has not decided yet rather than a school
        # asking us to guess from assigned lessons.
        await set_class_subjects(
            session,
            school_id=_school_of(user),
            class_id=school_class.id,
            typed=payload.subjects,
            created_by_user_id=user.id,
        )
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
    subjects = await subjects_for_class(session, class_id)
    return {
        "id": str(school_class.id),
        "name": school_class.name,
        "code": school_class.class_code,
        "yearGroup": school_class.year_group,
        "source": school_class.source,
        "subjects": subjects,
        "studentCount": students or 0,
        "archivedAt": school_class.archived_at,
    }


async def _student_counts(session: AsyncSession, class_ids: list[UUID]) -> dict[UUID, int]:
    """Enrolment counts for many classes in one query."""
    if not class_ids:
        return {}
    rows = await session.execute(
        select(
            StudentClassEnrollment.class_id,
            func.count(StudentClassEnrollment.id),
        )
        .where(StudentClassEnrollment.class_id.in_(class_ids))
        .group_by(StudentClassEnrollment.class_id)
    )
    return {class_id: int(total) for class_id, total in rows}


async def _teachers_by_class(
    session: AsyncSession, class_ids: list[UUID]
) -> dict[UUID, list[dict[str, object]]]:
    """Who holds each class, for many classes in one query.

    Names rather than a count: the screen is built around showing who teaches
    each class, and a count meant one more request per class to find out. The
    count is then just the length of this, so it is still one query for the
    whole page.
    """

    if not class_ids:
        return {}
    rows = await session.execute(
        select(
            TeacherClassAssignment.class_id,
            User.id,
            User.first_name,
            User.last_name,
            User.role,
        )
        .join(User, User.id == TeacherClassAssignment.teacher_id)
        .where(
            TeacherClassAssignment.class_id.in_(class_ids),
            TeacherClassAssignment.removed_at.is_(None),
        )
        .order_by(User.first_name, User.last_name)
    )
    by_class: dict[UUID, list[dict[str, object]]] = {}
    for class_id, teacher_id, first_name, last_name, role in rows:
        holders = by_class.setdefault(class_id, [])
        # One teacher can hold a class through more than one assignment row.
        if any(holder["id"] == str(teacher_id) for holder in holders):
            continue
        holders.append(
            {
                "id": str(teacher_id),
                "name": " ".join(part for part in (first_name, last_name) if part) or "Nevo user",
                "role": role.value if hasattr(role, "value") else str(role),
            }
        )
    return by_class


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
    consent = await student_consent_summaries(session, (item.id for item in students))
    return [
        {
            "id": str(item.id),
            "name": _name(item),
            "loginIdentifier": item.login_identifier,
            "status": item.status.value,
            "ageBand": coerce_band(item.age_band, item.date_of_birth),
            "consent": consent.get(item.id, empty_consent_summary()),
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
    # Students have no email and never will: the credential is a PIN and the
    # identity is the school's own admission number. SCRUM-202.
    admission_number = " ".join(payload.admission_number.split())
    taken = await session.scalar(
        select(User.id).where(
            User.school_id == actor.school_id,
            func.lower(User.admission_number) == admission_number.casefold(),
        )
    )
    if taken is not None:
        # Unique within the school, not globally: another school's 2024/001 is
        # a different child and does not block this one.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "admission_number_in_use",
                "message": (
                    f"{admission_number} already belongs to a learner at this school. "
                    "Two children cannot share one, because it is how each of them signs in."
                ),
            },
        )
    # Kept as the internal handle. The child never reads or types it; their
    # admission number is what they sign in with.
    identifier = f"NV-{secrets.token_hex(3).upper()}"
    student = User(
        school_id=actor.school_id,
        role=UserRole.STUDENT,
        auth_method=AuthMethod.PIN,
        first_name=payload.first_name,
        admission_number=admission_number,
        last_name=payload.last_name,
        login_identifier=identifier,
        # Derived from the date of birth where there is one, since that is the
        # fact the school actually holds and it stays true as the child ages.
        age_band=(band_for_date_of_birth(payload.date_of_birth) or payload.age_band),
        date_of_birth=payload.date_of_birth,
        status=UserStatus.ACTIVE,
    )
    session.add(student)
    await session.flush()
    session.add(StudentClassEnrollment(student_id=student.id, class_id=payload.class_id))
    if payload.parent_email:
        # Recorded now so the consent request has somewhere to go. The name is
        # left for the parent to supply when they answer: theirs is the version
        # the consent record should hold, and asking a proprietor to find it
        # first is what kept this field off the screen.
        session.add(
            ParentLink(
                school_id=actor.school_id,
                student_id=student.id,
                parent_name="",
                parent_contact=str(payload.parent_email).casefold(),
                contact_method=ParentContactMethod.EMAIL,
            )
        )
    session.add(
        EnrollmentHistory(
            student_id=student.id,
            to_class_id=payload.class_id,
            action="enrolled",
            actor_user_id=actor.id,
        )
    )
    try:
        await session.commit()
    except IntegrityError as error:
        # Two enrolments for the same address can both pass the check above
        # before either commits. The loser is a duplicate, not a fault.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "email_already_in_use",
                "message": "That email address already belongs to a Nevo account.",
            },
        ) from error
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
    consent = await student_consent_summaries(session, [student.id])
    return {
        "id": str(student.id),
        "firstName": student.first_name,
        "lastName": student.last_name,
        "loginIdentifier": student.login_identifier,
        "email": student.email,
        "status": student.status.value,
        "ageBand": coerce_band(student.age_band, student.date_of_birth),
        "classIds": [str(item) for item in class_ids],
        "firstUse": student.is_first_use,
        "consent": consent.get(student.id, empty_consent_summary()),
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
    anonymise_student(student, now=datetime.now(UTC))
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
    pin = f"{secrets.randbelow(10_000):04d}"
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
        "pinLength": 4,
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
    # CursorResult carries rowcount; the Result the stubs promise does not.
    if result.rowcount == 0:  # type: ignore[attr-defined]
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


@router.put(
    "/notification-preferences",
    response_model=NotificationPreferencesWriteResponse,
)
async def update_notification_preferences(
    payload: PreferenceWriteList,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    """Save notification preferences, row by row.

    An unknown category is rejected on its own line rather than failing the
    whole request. A settings screen posts every toggle in one call, so
    all-or-nothing meant one unrecognised category discarded the user's other,
    valid changes with nothing saved and nothing to show for it.
    """
    existing = {
        record.category: record
        for record in (
            await session.scalars(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == principal.user_id
                )
            )
        ).all()
    }
    saved: list[NotificationCategory] = []
    rejected: list[dict[str, str]] = []
    for item in payload:
        category = _known_category(item.category)
        if category is None:
            rejected.append(
                {
                    "category": str(item.category),
                    "reason": "unknown_category",
                }
            )
            continue
        record = existing.get(category)
        if record is None:
            record = NotificationPreference(
                user_id=principal.user_id,
                category=category,
            )
            session.add(record)
            existing[category] = record
        record.in_app = item.in_app
        record.email = item.email
        saved.append(category)
    await session.commit()
    return {
        "preferences": await notification_preferences(principal, session),
        "savedCount": len(saved),
        "rejected": rejected,
    }


def _known_category(value: str) -> NotificationCategory | None:
    try:
        return NotificationCategory(value)
    except ValueError:
        return None


@router.get("/settings/me", response_model=PersonalSettingsResponse)
async def personal_settings(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    user = await actor_user(session, principal)
    preferences = {**dict(user.preferences), "avatarTone": user.avatar_tone}
    return {"userId": str(user.id), "preferences": preferences}


@router.put("/settings/me", response_model=PersonalSettingsResponse)
async def update_personal_settings(
    payload: PersonalSettingsWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> dict[str, object]:
    """Merge preferences into what is stored.

    This used to replace the whole bag, while /api/settings/me merged into it.
    Same column, two write rules: a client using this one silently erased
    every key the other had set.
    """
    user = await actor_user(session, principal)
    if "avatarTone" in payload.preferences:
        user.avatar_tone = str(payload.preferences["avatarTone"] or "").strip()[:40] or None
    user.preferences = merge_preferences(user.preferences, payload.preferences)
    await session.commit()
    preferences = {**dict(user.preferences), "avatarTone": user.avatar_tone}
    return {"userId": str(user.id), "preferences": preferences}


def merge_preferences(
    stored: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    """One rule for both settings paths. Null removes a key."""
    merged = {**dict(stored), **incoming}
    return {key: value for key, value in merged.items() if value is not None}


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
