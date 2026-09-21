"""Consent collected on paper, recorded as the parent's rather than the school's.

Two things are wrong today and this closes both. A school with four hundred
children will not get four hundred email replies, so the children whose
parents never answered cannot learn - and where a school does confirm on a
parent's behalf, the record names the school administrator, so it does not
identify who consented at all.

Digital stays the default. This is the second route, and the record it writes
carries what the definition of a consent record asks for: who signed, their
relationship to the child, the date they signed, the method, the version of
the notice they were shown, and who uploaded the form.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import can_access_student, require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.consent.written import NOTICE_VERSION, render_consent_form
from nevo.db.models.account import ConsentRecord, School, User
from nevo.domain.accounts.vocabulary import (
    ConsentMethod,
    ConsentStatus,
    ConsentType,
)
from nevo.domain.consent.vocabulary import ConsentConfirmationSource
from nevo.storage import StorageError, SupabaseStorage

router = APIRouter(prefix="/api/v1", tags=["consent"])

SCHOOL_ROLES = {"senco_admin", "other_admin", "teacher"}

#: A phone photograph of a form, which is what a school office produces.
ACCEPTED_EVIDENCE = {"image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"}

MAX_EVIDENCE_BYTES = 10_000_000


class WrittenConsentResponse(CamelResponse):
    """What was recorded, in the terms the record now holds."""

    student_id: UUID
    consent_types: list[ConsentType]
    parent_name: str
    parent_relationship: str
    signed_on: date
    notice_version: str
    method: ConsentMethod
    evidence_storage_path: str | None
    uploaded_by: UUID
    uploaded_at: datetime
    #: True when the parent was told, which is how a withdrawal stays as easy
    #: as consenting for a parent who never touches the platform.
    parent_notified: bool


@router.get("/consents/form", response_class=Response)
async def download_consent_form(
    principal: PrincipalDependency,
    session: DatabaseSession,
    student_id: Annotated[UUID | None, Query(alias="studentId")] = None,
) -> Response:
    """The form Nevo supplies, printable at any time.

    Nevo's rather than the school's, because a school's own permission slip
    does not mention that lesson text is processed outside Nigeria, and that
    line has to be on the page a parent signs.
    """

    actor = await require_school_actor(session, principal, roles=SCHOOL_ROLES)
    school = await session.get(School, actor.school_id)
    student_name = None
    if student_id is not None:
        student = await _student(session, actor, student_id)
        student_name = " ".join(part for part in (student.first_name, student.last_name) if part)
    pdf = render_consent_form(
        school_name=school.name if school else "Your school",
        student_name=student_name,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="nevo-consent-form.pdf"',
            "X-Nevo-Notice-Version": NOTICE_VERSION,
        },
    )


@router.post(
    "/students/{student_id}/consents/written",
    response_model=WrittenConsentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_written_consent(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    parent_name: Annotated[str, Form(alias="parentName", min_length=2, max_length=255)],
    parent_relationship: Annotated[
        str,
        Form(alias="parentRelationship", min_length=2, max_length=80),
    ],
    signed_on: Annotated[date, Form(alias="signedOn")],
    consent_types: Annotated[list[ConsentType], Form(alias="consentTypes")],
    notice_version: Annotated[
        str,
        Form(alias="noticeVersion", max_length=40),
    ] = NOTICE_VERSION,
    form: Annotated[UploadFile | None, File()] = None,
) -> WrittenConsentResponse:
    """Record a signed form, with the parent named as the person who consented.

    The school is recorded as the uploader, not as the consenting party. Those
    are different facts and the record now keeps them apart.
    """

    actor = await require_school_actor(session, principal, roles=SCHOOL_ROLES)
    student = await _student(session, actor, student_id)
    if signed_on > datetime.now(UTC).date():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "signed_in_the_future",
                "message": "Check the date on the form: it is later than today.",
            },
        )
    storage_path = await _store_evidence(student_id, form)
    now = datetime.now(UTC)
    for consent_type in dict.fromkeys(consent_types):
        record = await session.scalar(
            select(ConsentRecord).where(
                ConsentRecord.subject_user_id == student_id,
                ConsentRecord.consent_type == consent_type,
            )
        )
        if record is None:
            record = ConsentRecord(subject_user_id=student_id, consent_type=consent_type)
            session.add(record)
        record.status = ConsentStatus.CONFIRMED
        record.confirmation_source = ConsentConfirmationSource.SCHOOL
        record.confirmed_by_admin_id = actor.id
        record.confirmed_by_parent_id = None
        record.confirmed_via = ConsentMethod.WRITTEN
        record.confirmed_at = now
        record.last_actor_user_id = actor.id
        record.last_changed_at = now
        record.last_channel = ConsentMethod.WRITTEN.value
        # The part that was missing: who actually consented.
        record.parent_name_on_form = parent_name.strip()
        record.parent_relationship = parent_relationship.strip()
        record.signed_on = signed_on
        record.notice_version = notice_version
        record.evidence_storage_path = storage_path
        record.uploaded_by_user_id = actor.id
        record.uploaded_at = now
    notified = await _tell_the_parent(session, student)
    await session.commit()
    return WrittenConsentResponse(
        student_id=student_id,
        consent_types=list(dict.fromkeys(consent_types)),
        parent_name=parent_name.strip(),
        parent_relationship=parent_relationship.strip(),
        signed_on=signed_on,
        notice_version=notice_version,
        method=ConsentMethod.WRITTEN,
        evidence_storage_path=storage_path,
        uploaded_by=actor.id,
        uploaded_at=now,
        parent_notified=notified,
    )


async def _student(session: DatabaseSession, actor: User, student_id: UUID) -> User:
    """The child this form is about, if this person may see them at all."""

    if not await can_access_student(session, actor, student_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    student = await session.get(User, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    return student


async def _store_evidence(student_id: UUID, form: UploadFile | None) -> str | None:
    """Keep the photograph of the form as the evidence behind the record."""

    if form is None:
        return None
    if form.content_type not in ACCEPTED_EVIDENCE:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "unsupported_evidence",
                "message": (
                    "Upload a photograph or a PDF of the signed form. A phone photograph is fine."
                ),
            },
        )
    raw = await form.read()
    if len(raw) > MAX_EVIDENCE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "evidence_too_large",
                "message": "That file is very large. A photograph of the page is enough.",
            },
        )
    storage = _storage()
    if not storage.configured:
        # The record is worth keeping even where the photograph cannot be:
        # refusing would lose the consent as well as the evidence.
        return None
    suffix = (form.filename or "form").rsplit(".", 1)[-1][:8] or "jpg"
    digest = hashlib.sha256(raw).hexdigest()
    path = f"consent/written/{student_id}/{digest}.{suffix}"
    try:
        await storage.upload(path, raw, content_type=form.content_type)
    except StorageError:
        return None
    return path


def _storage() -> SupabaseStorage:
    from nevo.audio.config import AudioSettings

    settings = AudioSettings()
    key = settings.supabase_service_role_key
    return SupabaseStorage(
        base_url=str(settings.supabase_url) if settings.supabase_url else None,
        service_role_key=key.get_secret_value() if key else None,
        bucket=settings.supabase_storage_bucket,
        # Never public: this is a photograph of a signed form carrying a
        # parent's name and signature.
        public=False,
        signed_url_ttl_seconds=settings.supabase_signed_url_ttl_seconds,
    )


async def _tell_the_parent(session: DatabaseSession, student: User) -> bool:
    """Tell the parent what was recorded, and how to undo it.

    Withdrawal has to be at least as easy as giving, and a parent who consented
    on paper and never touches the platform otherwise has no route at all
    unless they are sent one.
    """

    from nevo.db.models.consent import ParentLink
    from nevo.db.models.frontend_support import Notification
    from nevo.domain.accounts.vocabulary import (
        NotificationCategory,
        NotificationType,
        UserRole,
    )

    link = await session.scalar(
        select(ParentLink)
        .where(ParentLink.student_id == student.id)
        .order_by(ParentLink.created_at.desc())
    )
    if link is None or link.parent_id is None:
        return False
    session.add(
        Notification(
            recipient_id=link.parent_id,
            recipient_role=UserRole.PARENT_GUARDIAN.value,
            type=NotificationType.CONSENT_ACTION_REQUIRED.value,
            title="Your consent form has been recorded",
            description=(
                f"Your school recorded the form you signed for {student.first_name}. "
                "You can see what Nevo holds, and withdraw your consent, from "
                "your parent dashboard."
            ),
            navigates_to="/parent",
            category=NotificationCategory.CONSENT.value,
        )
    )
    return True
